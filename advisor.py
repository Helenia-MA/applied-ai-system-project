"""The generation half of the RAG feature: turn retrieved care guidance into
concrete, schedulable tasks.

Flow
----
    retrieval.retrieve(pet)  ->  chunks
    build the prompt from those chunks (and nothing else)
    one Gemini call, constrained to a JSON schema
    validate every suggestion, drop the ones that fail
    ->  list[CareSuggestion], ready for Pet.accept_suggestion()

The output is deliberately *structured* rather than prose. Prose would only be
printable alongside the existing plan; typed task fields feed straight into the
scheduler, which is what makes retrieval change the plan instead of decorating
it.

Design notes
------------
Grounding is enforced twice. The prompt tells the model to work only from the
supplied chunks and to cite the chunk id behind each suggestion; then
`_validate` rejects any suggestion whose citation is not one of the ids actually
retrieved. The second check is the one that matters, because it does not depend
on the model cooperating.

Nothing here mutates the pet. Suggestions are advisory until an owner accepts
one, so a bad generation can never silently rewrite somebody's schedule.
"""

from __future__ import annotations

import logging
import os
import re
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Literal

from pydantic import BaseModel, ValidationError

import retrieval
from pawpal_system import PRIORITY_VALUES

if TYPE_CHECKING:  # pragma: no cover - import only for type checkers
    from pawpal_system import Pet
    from retrieval import Chunk


logger = logging.getLogger(__name__)

# Load a .env file if python-dotenv is installed. Optional so the module still
# imports cleanly without it — the app also runs from plain exported env vars.
try:  # pragma: no cover - depends on the local environment
    from dotenv import load_dotenv

    load_dotenv()
except ImportError:  # pragma: no cover
    pass


# Verified working on a new free-tier key. Gemini retires models fairly often —
# gemini-2.5-flash was closed to new keys while this was being written — so if
# this 404s, `PAWPAL_MODEL=gemini-flash-latest` is an alias that tracks whatever
# the current flash model is.
DEFAULT_MODEL = "gemini-3.6-flash"

# Both names work. GEMINI_API_KEY is what AI Studio hands you; GOOGLE_API_KEY is
# what the SDK reads implicitly. We read them ourselves and pass the key
# explicitly, so behaviour doesn't depend on which one the SDK happens to check.
API_KEY_VARS = ("GEMINI_API_KEY", "GOOGLE_API_KEY")

# Generous enough that any internal reasoning plus the JSON response both fit —
# a tight limit here would truncate the JSON mid-object.
MAX_OUTPUT_TOKENS = 4096

# Finish reasons that mean the model stopped for a content-policy reason rather
# than because it was done. Grouped so all of them get the same handling.
_BLOCKED_FINISH_REASONS = frozenset({
    "SAFETY", "PROHIBITED_CONTENT", "BLOCKLIST", "SPII", "RECITATION", "IMAGE_SAFETY",
})

# Ceiling on accepted suggestions. Bounds how much a single call can add to a
# schedule, independent of what the model returns.
MAX_SUGGESTIONS = 5

# Sanity bounds for validation. A task outside these isn't a routine care task,
# so it's a sign the model drifted rather than something worth clamping.
MIN_DURATION_MINUTES = 1
MAX_DURATION_MINUTES = 240
MAX_NAME_LENGTH = 60

_TIME_PATTERN = re.compile(r"^(\d{1,2}):([0-5]\d)$")

SYSTEM_PROMPT = """You suggest routine pet-care tasks for a scheduling app.

Work only from the CARE GUIDANCE in the user message. Every suggestion must \
restate care that appears in one of those numbered chunks, and must cite that \
chunk's id in source_chunk_id. If the guidance doesn't support a task, don't \
suggest it — returning fewer suggestions, or none at all, is the correct answer \
when the guidance is thin.

Take duration_minutes and frequency from the numbers stated in the guidance \
rather than estimating them. Choose a sensible clock time for each task; when \
the guidance says something happens twice daily twelve hours apart, space the \
times accordingly.

Don't suggest a task that duplicates one the pet already has, and don't put a \
task at a clock time the pet already has something scheduled at — the owner is \
one person and can only do one thing at a time.

Don't diagnose, adjust medication, or add advice that isn't in the guidance text.

Suggest at most five tasks, most important first. When one chunk describes \
several things, lead with the one it presents as most valuable.

Keep rationale to one sentence naming the care need the task addresses."""


class SuggestedTask(BaseModel):
    """One task as the model returns it, before validation.

    Priority uses the same words the UI shows rather than the integers the
    scheduler stores — the model handles "high" more reliably than "3", and
    `_validate` does the conversion.
    """

    name: str
    duration_minutes: int
    priority: Literal["high", "medium", "low"]
    time: str
    frequency: Literal["daily", "weekly", "once"]
    source_chunk_id: str
    rationale: str


class SuggestionBatch(BaseModel):
    """Top-level schema for the response. Structured outputs need an object."""

    suggestions: list[SuggestedTask]


@dataclass(frozen=True)
class CareSuggestion:
    """A validated suggestion, in the shape `Pet.add_task` expects.

    `priority` is already the scheduler's integer, and `source_chunk_id` is
    guaranteed to be a chunk that was genuinely retrieved — so the UI can show
    the owner which piece of guidance produced this task.
    """

    name: str
    duration_minutes: int
    priority: int
    time: str
    frequency: str
    source_chunk_id: str
    rationale: str


@dataclass
class AdvisorResult:
    """Everything the caller needs to render and audit one suggestion request.

    `available` is False whenever no model call happened — no API key, the
    feature switched off, nothing retrieved, or the call failed. `reason` then
    holds a message fit to show the user. The scheduler keeps working either way;
    that's the point of returning a result object instead of raising.
    """

    suggestions: list[CareSuggestion] = field(default_factory=list)
    chunk_ids: list[str] = field(default_factory=list)
    available: bool = False
    reason: str = ""
    model: str = ""
    usage: dict[str, int] = field(default_factory=dict)
    rejected: list[str] = field(default_factory=list)


# --- Configuration --------------------------------------------------------

def api_key() -> str:
    """The configured Gemini API key, or "" if there isn't one."""
    for name in API_KEY_VARS:
        value = os.environ.get(name, "").strip()
        if value:
            return value
    return ""


def _switched_off() -> bool:
    """Whether USE_LLM explicitly disables the feature."""
    return os.environ.get("USE_LLM", "1").strip().lower() in {"0", "false", "no", "off"}


def llm_enabled() -> bool:
    """Whether suggestions should attempt a model call.

    Two ways to switch off: no API key, or USE_LLM set to a false-ish value.
    The explicit flag exists so the app and its demo can be run and graded
    without credentials.
    """
    return not _switched_off() and bool(api_key())


def unavailable_reason() -> str:
    """A user-facing explanation of why suggestions are switched off."""
    if _switched_off():
        return "AI suggestions are disabled (USE_LLM is off)."
    if not api_key():
        return "AI suggestions need GEMINI_API_KEY to be set."
    return ""


def _build_client() -> Any:
    """Create the Gemini client.

    Imported here rather than at module scope so `import advisor` works without
    the SDK installed — the tests exercise prompt building and validation with
    an injected fake client and never touch the real one.
    """
    from google import genai

    return genai.Client(api_key=api_key())


# --- Prompt assembly ------------------------------------------------------

def format_chunks(chunks: list["Chunk"]) -> str:
    """Render retrieved chunks as the numbered, id-labelled context block.

    Ids are shown because the model has to cite one per suggestion, and that
    citation is what `_validate` checks against.
    """
    return "\n\n".join(
        f"[{index}] id: {chunk.id}\n{chunk.text}"
        for index, chunk in enumerate(chunks, start=1)
    )


def build_user_message(pet: "Pet", chunks: list["Chunk"]) -> str:
    """Assemble the user turn: pet profile, existing tasks, retrieved guidance.

    Existing tasks are included so the model can avoid re-suggesting them; the
    duplicate check in `_validate` is the backstop for when it does anyway.
    """
    profile = [f"Name: {pet.name}", f"Species: {pet.species or 'unknown'}"]
    if pet.breed:
        profile.append(f"Breed: {pet.breed}")
    if pet.age is not None:
        profile.append(f"Age: {pet.age} years")
    if pet.medical_condition:
        profile.append(f"Medical condition: {pet.medical_condition}")
    profile.append(f"Time available today: {pet.available_minutes} minutes")

    # Times are included, not just names: without them the model can't avoid
    # scheduling on top of an existing task, and the scheduler would then flag a
    # time conflict that was entirely avoidable.
    existing = [f"{task.name} at {task.time}" for task in pet.tasks if not task.completed]
    existing_text = ", ".join(existing) if existing else "(none yet)"

    return (
        "PET PROFILE\n"
        + "\n".join(profile)
        + f"\n\nEXISTING TASKS\n{existing_text}"
        + f"\n\nCARE GUIDANCE\n{format_chunks(chunks)}"
        + "\n\nSuggest care tasks for this pet based on the guidance above."
    )


# --- Validation -----------------------------------------------------------

def _normalize_time(value: str) -> str | None:
    """Zero-pad a valid "H:MM" or "HH:MM" clock time, or return None.

    Formatting is normalised rather than rejected — "7:30" is unambiguous and
    the scheduler sorts times as strings, so it only needs the padding. An hour
    above 23 is a real error, not a formatting one.
    """
    match = _TIME_PATTERN.match(value.strip())
    if not match:
        return None
    hour, minute = int(match.group(1)), match.group(2)
    if hour > 23:
        return None
    return f"{hour:02d}:{minute}"


def _validate(
    task: SuggestedTask,
    valid_chunk_ids: set[str],
    existing_names: set[str],
) -> tuple[CareSuggestion | None, str]:
    """Check one suggestion, returning either the validated form or a reason.

    Rejections are returned rather than raised so one bad suggestion costs that
    suggestion and not the whole batch. Each reason is logged and surfaced in
    `AdvisorResult.rejected`, which is what makes the guardrail auditable
    instead of invisible.
    """
    name = " ".join(task.name.split())
    if not name:
        return None, "empty task name"
    if len(name) > MAX_NAME_LENGTH:
        return None, f"task name longer than {MAX_NAME_LENGTH} characters: {name[:40]!r}"

    # The anti-hallucination check: a citation the retrieval step never returned
    # means the suggestion isn't grounded in this pet's guidance, whatever the
    # model claimed.
    chunk_id = retrieval._normalize(task.source_chunk_id)
    if chunk_id not in valid_chunk_ids:
        return None, f"{name!r} cites unretrieved chunk {task.source_chunk_id!r}"

    if not MIN_DURATION_MINUTES <= task.duration_minutes <= MAX_DURATION_MINUTES:
        return None, (
            f"{name!r} has out-of-range duration {task.duration_minutes} min"
        )

    clock_time = _normalize_time(task.time)
    if clock_time is None:
        return None, f"{name!r} has unparseable time {task.time!r}"

    if name.lower() in existing_names:
        return None, f"{name!r} duplicates an existing task"

    return (
        CareSuggestion(
            name=name,
            duration_minutes=task.duration_minutes,
            priority=PRIORITY_VALUES[task.priority],
            time=clock_time,
            frequency=task.frequency,
            source_chunk_id=chunk_id,
            rationale=" ".join(task.rationale.split()),
        ),
        "",
    )


def validate_batch(
    batch: SuggestionBatch,
    chunks: list["Chunk"],
    pet: "Pet",
) -> tuple[list[CareSuggestion], list[str]]:
    """Validate a whole batch, returning what survived and why the rest didn't.

    Also drops suggestions that duplicate each other, since two identical tasks
    would only trip the scheduler's own duplicate warning later.
    """
    valid_chunk_ids = {chunk.id for chunk in chunks}
    existing_names = {task.name.lower() for task in pet.tasks}

    accepted: list[CareSuggestion] = []
    rejected: list[str] = []

    for task in batch.suggestions:
        if len(accepted) >= MAX_SUGGESTIONS:
            rejected.append(f"{task.name!r} dropped: over the {MAX_SUGGESTIONS}-suggestion cap")
            continue

        suggestion, reason = _validate(task, valid_chunk_ids, existing_names)
        if suggestion is None:
            rejected.append(f"rejected: {reason}")
            continue

        accepted.append(suggestion)
        # Treat an accepted name as taken, so the batch can't contain duplicates.
        existing_names.add(suggestion.name.lower())

    for reason in rejected:
        logger.warning("Suggestion %s", reason)

    return accepted, rejected


# --- The model call -------------------------------------------------------

def suggest_care_tasks(
    pet: "Pet",
    *,
    client: Any | None = None,
    chunks: list["Chunk"] | None = None,
    model: str | None = None,
) -> AdvisorResult:
    """Retrieve care guidance for `pet`, then ask Claude for schedulable tasks.

    Never raises. Every failure path — feature off, nothing retrieved, API
    error, malformed response — comes back as an `AdvisorResult` with
    `available=False` and a `reason` fit to display, so the scheduling side of
    the app is unaffected by anything that goes wrong here.

    `client` and `chunks` are injectable so tests can run the whole path offline.
    """
    model_name = model or os.environ.get("PAWPAL_MODEL", DEFAULT_MODEL)

    if client is None and not llm_enabled():
        reason = unavailable_reason()
        logger.info("Skipping suggestions for %s: %s", pet.name, reason)
        return AdvisorResult(available=False, reason=reason)

    # Retrieval first — this is the "R" the whole feature turns on.
    try:
        selected = chunks if chunks is not None else retrieval.retrieve(pet)
    except retrieval.KnowledgeBaseError as error:
        logger.error("Knowledge base unavailable: %s", error)
        return AdvisorResult(
            available=False,
            reason="The care knowledge base could not be loaded.",
        )

    if not selected:
        # No grounding means no honest answer. Asking anyway would just invite
        # the model to invent care advice.
        reason = (
            f"No care guidance matches {pet.name}'s profile — "
            "add a species (and ideally breed or age) first."
        )
        logger.info("Skipping suggestions for %s: nothing retrieved", pet.name)
        return AdvisorResult(available=False, reason=reason, chunk_ids=[])

    chunk_ids = [chunk.id for chunk in selected]

    if client is None:
        try:
            client = _build_client()
        except ImportError:
            logger.error("The google-genai package is not installed")
            return AdvisorResult(
                available=False,
                reason="The google-genai package is not installed. Run: pip install -r requirements.txt",
                chunk_ids=chunk_ids,
            )

    logger.info(
        "Requesting suggestions for %s from %s, grounded in: %s",
        pet.name, model_name, ", ".join(chunk_ids),
    )

    try:
        response = client.models.generate_content(
            model=model_name,
            contents=build_user_message(pet, selected),
            config={
                "system_instruction": SYSTEM_PROMPT,
                # Both keys are needed together: the mime type turns on JSON mode
                # and the schema constrains its shape to SuggestionBatch.
                "response_mime_type": "application/json",
                "response_schema": SuggestionBatch,
                "max_output_tokens": MAX_OUTPUT_TOKENS,
            },
        )
    except Exception as error:  # noqa: BLE001 - mapped to a message below
        reason = _describe_api_error(error)
        logger.error("Suggestion request for %s failed: %s", pet.name, error)
        return AdvisorResult(available=False, reason=reason, chunk_ids=chunk_ids,
                            model=model_name)

    usage = _extract_usage(response)
    if usage:
        logger.info("Token usage for %s: %s", pet.name, usage)

    def failed(reason: str) -> AdvisorResult:
        return AdvisorResult(available=False, reason=reason, chunk_ids=chunk_ids,
                             model=model_name, usage=usage)

    # Why generation stopped has to be checked before the payload is trusted:
    # a blocked or truncated response leaves `parsed` empty or partial.
    #
    # Gemini can block at two different levels, which is why this is two checks
    # rather than one. A prompt-level block means the request never reached the
    # model; a candidate-level block means it did and the output was withheld.
    prompt_block = _prompt_block_reason(response)
    if prompt_block:
        logger.warning("Prompt blocked for %s (%s)", pet.name, prompt_block)
        return failed(
            "The request was blocked by a content filter. Try simplifying the pet's notes."
        )

    finish_reason = _finish_reason(response)
    if finish_reason in _BLOCKED_FINISH_REASONS:
        logger.warning("Response blocked for %s (%s)", pet.name, finish_reason)
        return failed(
            "The response was withheld by a content filter. Try simplifying the pet's notes."
        )
    if finish_reason == "MAX_TOKENS":
        logger.warning("Suggestion response for %s hit the token limit", pet.name)
        return failed("The response was cut off before it finished. Please try again.")

    batch = getattr(response, "parsed", None)
    if not isinstance(batch, SuggestionBatch):
        # Covers an empty response, and the case where JSON mode returned
        # something the schema couldn't be built from.
        logger.warning("No usable parsed output for %s (finish_reason=%s)",
                       pet.name, finish_reason or "unknown")
        return failed("The model's response could not be read. Please try again.")

    accepted, rejected = validate_batch(batch, selected, pet)

    logger.info(
        "Accepted %d of %d suggestions for %s (%d rejected)",
        len(accepted), len(batch.suggestions), pet.name, len(rejected),
    )

    reason = ""
    if not accepted:
        reason = (
            "No suggestions passed validation — the retrieved guidance may not "
            "cover anything beyond this pet's existing tasks."
        )

    return AdvisorResult(
        suggestions=accepted,
        chunk_ids=chunk_ids,
        available=True,
        reason=reason,
        model=model_name,
        usage=usage,
        rejected=rejected,
    )


def _enum_name(value: Any) -> str:
    """Normalise an enum, string, or None to an uppercase name.

    Gemini returns real enum members, but reading `.name` defensively keeps this
    working against the plain strings the test doubles use.
    """
    if value is None:
        return ""
    return str(getattr(value, "name", value)).upper()


def _prompt_block_reason(response: Any) -> str:
    """The prompt-level block reason, or "" if the prompt wasn't blocked."""
    feedback = getattr(response, "prompt_feedback", None)
    if feedback is None:
        return ""
    return _enum_name(getattr(feedback, "block_reason", None))


def _finish_reason(response: Any) -> str:
    """The first candidate's finish reason, or "" if there is no candidate."""
    candidates = getattr(response, "candidates", None) or []
    if not candidates:
        return ""
    return _enum_name(getattr(candidates[0], "finish_reason", None))


def _extract_usage(response: Any) -> dict[str, int]:
    """Pull token counts off the response for the log, tolerating absence.

    Written defensively because the fake clients in the tests don't carry a usage
    object, and cost logging shouldn't be able to break a working call.
    """
    usage = getattr(response, "usage_metadata", None)
    if usage is None:
        return {}
    fields = ("prompt_token_count", "candidates_token_count",
              "thoughts_token_count", "cached_content_token_count",
              "total_token_count")
    return {
        name: getattr(usage, name)
        for name in fields
        if isinstance(getattr(usage, name, None), int)
    }


def _describe_api_error(error: Exception) -> str:
    """Map an SDK exception to a message worth showing an owner.

    Matched against the SDK's typed exception classes and HTTP status codes
    rather than by inspecting error strings. If the SDK isn't importable we still
    return something useful, since this path also covers schema-validation
    failures.
    """
    if isinstance(error, ValidationError):
        return "The model's response didn't match the expected format. Please try again."

    try:
        from google.genai import errors
    except ImportError:  # pragma: no cover - only without the SDK installed
        return f"Suggestions are unavailable: {error}"

    if isinstance(error, errors.APIError):
        code = getattr(error, "code", None)
        if code in (401, 403):
            return "GEMINI_API_KEY was rejected. Check the key and try again."
        if code == 404:
            return f"Model {os.environ.get('PAWPAL_MODEL', DEFAULT_MODEL)!r} isn't available to this key. Check PAWPAL_MODEL."
        if code == 429:
            # The likeliest failure on the free tier, so it gets its own advice.
            return "Rate limited by the free tier. Wait a minute and try again."
        if code == 400:
            return f"The API rejected the request: {getattr(error, 'message', error)}"
        if isinstance(error, errors.ServerError):
            return f"The API returned a server error (status {code}). Try again shortly."
        return f"The API returned an error (status {code}): {getattr(error, 'message', error)}"

    # Anything else is almost always a transport failure, since APIError covers
    # every response the API actually returned.
    return f"Could not reach the API: {error}"
