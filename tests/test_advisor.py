"""Tests for the generation half of the RAG feature (advisor.py).

Every test here runs offline. A fake client stands in for the Anthropic SDK, so
the whole path — prompt assembly, response handling, validation, error handling —
is exercised without an API key or a network call.

That matters for two reasons: the grading criteria ask that the project run
reproducibly for someone else, and the guardrails are only worth having if their
failure paths are actually tested.
"""

import pytest
from pydantic import ValidationError

import advisor
from advisor import (
    AdvisorResult,
    CareSuggestion,
    SuggestedTask,
    SuggestionBatch,
    build_user_message,
    format_chunks,
    suggest_care_tasks,
    validate_batch,
)
from pawpal_system import PRIORITY_VALUES, Pet
from retrieval import Chunk


# --- Test doubles ---------------------------------------------------------

CHUNKS = [
    Chunk(id="dog-hip-dysplasia", text="Swimming for 15 to 20 minutes is ideal.",
          species=("dog",), conditions=("hip dysplasia",), avoid=("stairs",)),
    Chunk(id="dog-general-dental", text="Brush teeth for 5 minutes daily.",
          species=("dog",), always=True),
]


class FakeModels:
    """Stands in for `client.models`, recording the call it was given."""

    def __init__(self, response):
        self._response = response
        self.calls = []

    def generate_content(self, **kwargs):
        self.calls.append(kwargs)
        if isinstance(self._response, Exception):
            raise self._response
        return self._response


class FakeClient:
    """Minimal stand-in for `genai.Client()`."""

    def __init__(self, response):
        self.models = FakeModels(response)


class FakeCandidate:
    """One candidate, carrying the finish reason.

    `finish_reason` is a plain string here where the SDK returns a FinishReason
    enum; advisor reads it through `_enum_name`, which handles both.
    """

    def __init__(self, finish_reason="STOP"):
        self.finish_reason = finish_reason


class FakePromptFeedback:
    def __init__(self, block_reason=None):
        self.block_reason = block_reason


class FakeResponse:
    """Stands in for the GenerateContentResponse that generate_content returns."""

    def __init__(self, parsed=None, finish_reason="STOP", usage_metadata=None,
                 block_reason=None):
        self.parsed = parsed
        self.candidates = [FakeCandidate(finish_reason)]
        self.usage_metadata = usage_metadata
        self.prompt_feedback = FakePromptFeedback(block_reason) if block_reason else None


class FakeUsage:
    def __init__(self, prompt_token_count=1200, candidates_token_count=180):
        self.prompt_token_count = prompt_token_count
        self.candidates_token_count = candidates_token_count


def suggested(**overrides):
    """A valid SuggestedTask, with fields overridable per test."""
    fields = {
        "name": "Swim session",
        "duration_minutes": 20,
        "priority": "high",
        "time": "09:00",
        "frequency": "daily",
        "source_chunk_id": "dog-hip-dysplasia",
        "rationale": "Low-impact exercise for the affected joint.",
    }
    fields.update(overrides)
    return SuggestedTask(**fields)


def dog_with_dysplasia():
    return Pet("Biscuit", "dog", available_minutes=60,
               medical_condition="hip dysplasia")


def call_with(tasks, pet=None, **kwargs):
    """Run the full advisor path against a fake client returning `tasks`."""
    client = FakeClient(FakeResponse(SuggestionBatch(suggestions=tasks),
                                    usage_metadata=FakeUsage()))
    result = suggest_care_tasks(pet or dog_with_dysplasia(),
                                client=client, chunks=CHUNKS, **kwargs)
    return result, client


# --- Feature: prompt assembly is grounded in retrieved chunks -------------

def test_format_chunks_labels_every_chunk_with_its_id():
    """The model needs the ids visible, because it must cite one per suggestion."""
    rendered = format_chunks(CHUNKS)

    assert "id: dog-hip-dysplasia" in rendered
    assert "id: dog-general-dental" in rendered
    assert "Swimming for 15 to 20 minutes" in rendered


def test_user_message_contains_profile_existing_tasks_and_guidance():
    """All three inputs reach the prompt: who the pet is, what it has, what we know."""
    pet = dog_with_dysplasia()
    pet.add_task("Morning walk", 30, PRIORITY_VALUES["high"])

    message = build_user_message(pet, CHUNKS)

    assert "Biscuit" in message
    assert "hip dysplasia" in message
    assert "Morning walk" in message          # so the model won't re-suggest it
    assert "dog-hip-dysplasia" in message     # the retrieved guidance


def test_existing_tasks_are_listed_with_their_times():
    """Times matter as much as names: without them the model books over a task."""
    pet = dog_with_dysplasia()
    pet.add_task("Morning walk", 30, PRIORITY_VALUES["high"], time="08:00")

    assert "Morning walk at 08:00" in build_user_message(pet, CHUNKS)


def test_user_message_omits_profile_fields_that_are_unset():
    """A sparse profile produces a sparse prompt rather than 'Breed: None'."""
    message = build_user_message(Pet("Plain", "cat"), CHUNKS)

    assert "Breed:" not in message
    assert "Age:" not in message
    assert "Medical condition:" not in message


def test_completed_tasks_are_not_listed_as_existing():
    """Only outstanding tasks are worth telling the model about."""
    pet = dog_with_dysplasia()
    task = pet.add_task("Old task", 10, PRIORITY_VALUES["low"])
    task.mark_complete()

    assert "(none yet)" in build_user_message(pet, CHUNKS)


# --- Feature: the happy path produces schedulable tasks -------------------

def test_valid_suggestion_becomes_a_care_suggestion():
    """A well-formed response comes back as tasks in the scheduler's own shape."""
    result, _ = call_with([suggested()])

    assert result.available is True
    assert len(result.suggestions) == 1

    suggestion = result.suggestions[0]
    assert isinstance(suggestion, CareSuggestion)
    assert suggestion.name == "Swim session"
    assert suggestion.duration_minutes == 20
    # Priority arrives as a word and is stored as the scheduler's integer.
    assert suggestion.priority == PRIORITY_VALUES["high"]
    assert suggestion.source_chunk_id == "dog-hip-dysplasia"


def test_result_records_the_chunks_and_model_used():
    """The result carries its own audit trail for the UI and the logs."""
    result, _ = call_with([suggested()], model="gemini-2.5-flash")

    assert result.chunk_ids == ["dog-hip-dysplasia", "dog-general-dental"]
    assert result.model == "gemini-2.5-flash"
    assert result.usage["prompt_token_count"] == 1200


def test_the_retrieved_guidance_is_what_gets_sent():
    """Confirms retrieval feeds generation, rather than running alongside it."""
    _, client = call_with([suggested()])

    sent = client.models.calls[0]["contents"]
    assert "Swimming for 15 to 20 minutes is ideal." in sent


def test_the_response_is_schema_constrained():
    """JSON mode plus the schema are what make the output parseable, not prose."""
    _, client = call_with([suggested()])
    config = client.models.calls[0]["config"]

    assert config["response_mime_type"] == "application/json"
    assert config["response_schema"] is SuggestionBatch
    assert config["system_instruction"] is advisor.SYSTEM_PROMPT


# --- Feature: guardrail — suggestions must cite retrieved guidance --------

def test_suggestion_citing_an_unretrieved_chunk_is_rejected():
    """The anti-hallucination check, and the one that doesn't trust the model.

    A citation that retrieval never returned means the suggestion isn't grounded
    in this pet's guidance, whatever the model claimed in its rationale.
    """
    result, _ = call_with([suggested(source_chunk_id="cat-kidney-disease")])

    assert result.suggestions == []
    assert any("cites unretrieved chunk" in reason for reason in result.rejected)


def test_a_bad_suggestion_does_not_discard_the_good_ones():
    """Validation is per-suggestion, so one bad entry costs only itself."""
    result, _ = call_with([
        suggested(name="Ungrounded task", source_chunk_id="made-up-id"),
        suggested(name="Tooth brushing", duration_minutes=5,
                  source_chunk_id="dog-general-dental"),
    ])

    assert [s.name for s in result.suggestions] == ["Tooth brushing"]
    assert len(result.rejected) == 1


# --- Feature: guardrail — field validation --------------------------------

@pytest.mark.parametrize("duration", [0, -5, 500])
def test_out_of_range_durations_are_rejected(duration):
    """A task outside sane bounds signals drift, not a value worth clamping."""
    result, _ = call_with([suggested(duration_minutes=duration)])

    assert result.suggestions == []
    assert any("duration" in reason for reason in result.rejected)


@pytest.mark.parametrize("bad_time", ["25:00", "9pm", "0900", "", "12:60"])
def test_unparseable_times_are_rejected(bad_time):
    """The scheduler sorts times as strings, so a malformed time would misorder."""
    result, _ = call_with([suggested(time=bad_time)])

    assert result.suggestions == []
    assert any("time" in reason for reason in result.rejected)


def test_short_form_times_are_normalized_rather_than_rejected():
    """"7:30" is unambiguous; it just needs zero-padding to sort correctly."""
    result, _ = call_with([suggested(time="7:30")])

    assert result.suggestions[0].time == "07:30"


def test_empty_task_names_are_rejected():
    """A nameless task would render as a blank row in the plan."""
    result, _ = call_with([suggested(name="   ")])

    assert result.suggestions == []
    assert any("empty task name" in reason for reason in result.rejected)


def test_overlong_task_names_are_rejected():
    """Names are displayed in a fixed-width column, so length is bounded."""
    result, _ = call_with([suggested(name="x" * 200)])

    assert result.suggestions == []
    assert any("longer than" in reason for reason in result.rejected)


def test_invalid_priority_never_reaches_validation():
    """The schema itself constrains priority, so bad values fail at parse time."""
    with pytest.raises(ValidationError):
        suggested(priority="urgent")


# --- Feature: guardrail — no duplicate tasks ------------------------------

def test_suggestion_duplicating_an_existing_task_is_rejected():
    """Re-suggesting a task the owner already has would only add a conflict."""
    pet = dog_with_dysplasia()
    pet.add_task("Swim session", 20, PRIORITY_VALUES["high"])

    result, _ = call_with([suggested(name="Swim session")], pet=pet)

    assert result.suggestions == []
    assert any("duplicates an existing task" in reason for reason in result.rejected)


def test_duplicate_suggestions_within_one_batch_are_collapsed():
    """The batch can't contain the same task twice, even if the model repeats it."""
    result, _ = call_with([suggested(), suggested()])

    assert len(result.suggestions) == 1


def test_the_suggestion_cap_is_enforced():
    """A single call can only add so much to a schedule, whatever comes back."""
    many = [suggested(name=f"Task {index}") for index in range(12)]

    result, _ = call_with(many)

    assert len(result.suggestions) == advisor.MAX_SUGGESTIONS
    assert any("cap" in reason for reason in result.rejected)


# --- Feature: graceful degradation ----------------------------------------

def test_no_retrieved_guidance_means_no_model_call():
    """With nothing retrieved there's no honest answer, so we don't ask.

    Calling anyway would invite the model to invent care advice, which is the
    failure mode grounding exists to prevent.
    """
    client = FakeClient(FakeResponse(SuggestionBatch(suggestions=[suggested()])))

    result = suggest_care_tasks(Pet("Mystery"), client=client, chunks=[])

    assert result.available is False
    assert "No care guidance matches" in result.reason
    assert client.models.calls == []  # never called


def test_missing_api_key_disables_suggestions_without_raising(monkeypatch):
    """The scheduler must keep working when credentials aren't configured."""
    for name in advisor.API_KEY_VARS:
        monkeypatch.delenv(name, raising=False)
    monkeypatch.delenv("USE_LLM", raising=False)

    result = suggest_care_tasks(dog_with_dysplasia())

    assert result.available is False
    assert "GEMINI_API_KEY" in result.reason


def test_either_api_key_variable_is_accepted(monkeypatch):
    """GEMINI_API_KEY is what AI Studio gives you; GOOGLE_API_KEY is the SDK's name."""
    for name in advisor.API_KEY_VARS:
        monkeypatch.delenv(name, raising=False)
    monkeypatch.delenv("USE_LLM", raising=False)
    assert advisor.llm_enabled() is False

    monkeypatch.setenv("GOOGLE_API_KEY", "test-key")
    assert advisor.llm_enabled() is True


def test_use_llm_flag_switches_the_feature_off(monkeypatch):
    """An explicit off switch, so the app can be demoed and graded without a key."""
    monkeypatch.setenv("GEMINI_API_KEY", "test-key-not-real")
    monkeypatch.setenv("USE_LLM", "0")

    result = suggest_care_tasks(dog_with_dysplasia())

    assert result.available is False
    assert "disabled" in result.reason


def test_knowledge_base_failure_is_reported_not_raised(monkeypatch):
    """A missing knowledge base disables suggestions; it doesn't crash the app."""
    def boom(_pet):
        raise advisor.retrieval.KnowledgeBaseError("file missing")

    monkeypatch.setattr(advisor.retrieval, "retrieve", boom)
    client = FakeClient(FakeResponse())

    result = suggest_care_tasks(dog_with_dysplasia(), client=client)

    assert result.available is False
    assert "knowledge base" in result.reason.lower()


# --- Feature: error handling on the model call ----------------------------

def test_transport_errors_are_caught_and_described():
    """Any exception from the SDK becomes a displayable reason, never a traceback."""
    client = FakeClient(RuntimeError("connection reset"))

    result = suggest_care_tasks(dog_with_dysplasia(), client=client, chunks=CHUNKS)

    assert result.available is False
    assert "connection reset" in result.reason
    # The chunk ids are still reported, so the log shows how far the call got.
    assert result.chunk_ids == ["dog-hip-dysplasia", "dog-general-dental"]


def test_schema_validation_failure_is_reported_clearly():
    """A response that doesn't match the schema gets its own message."""
    error = ValidationError.from_exception_data("SuggestionBatch", [])
    client = FakeClient(error)

    result = suggest_care_tasks(dog_with_dysplasia(), client=client, chunks=CHUNKS)

    assert result.available is False
    assert "expected format" in result.reason


def test_a_prompt_level_block_is_handled():
    """Gemini can block before the model runs, leaving no candidate at all.

    This is one of two block levels, which is why the check isn't a single
    branch: a prompt-level block means the request never reached the model.
    """
    client = FakeClient(FakeResponse(parsed=None, block_reason="SAFETY"))

    result = suggest_care_tasks(dog_with_dysplasia(), client=client, chunks=CHUNKS)

    assert result.available is False
    assert "blocked by a content filter" in result.reason


@pytest.mark.parametrize("reason", ["SAFETY", "PROHIBITED_CONTENT", "BLOCKLIST", "SPII"])
def test_a_candidate_level_block_is_handled(reason):
    """The other block level: the model ran, but its output was withheld."""
    client = FakeClient(FakeResponse(parsed=None, finish_reason=reason))

    result = suggest_care_tasks(dog_with_dysplasia(), client=client, chunks=CHUNKS)

    assert result.available is False
    assert "withheld by a content filter" in result.reason


def test_a_truncated_response_is_handled_before_reading_the_payload():
    """Hitting the token limit can leave partial JSON, so it's caught up front."""
    client = FakeClient(FakeResponse(parsed=None, finish_reason="MAX_TOKENS"))

    result = suggest_care_tasks(dog_with_dysplasia(), client=client, chunks=CHUNKS)

    assert result.available is False
    assert "cut off" in result.reason


def test_finish_reason_is_read_from_an_enum_as_well_as_a_string():
    """The SDK returns a FinishReason enum, so `.name` has to be handled."""
    from google.genai import types

    client = FakeClient(FakeResponse(parsed=None,
                                     finish_reason=types.FinishReason.MAX_TOKENS))

    result = suggest_care_tasks(dog_with_dysplasia(), client=client, chunks=CHUNKS)

    assert "cut off" in result.reason


def test_missing_parsed_output_is_handled():
    """Defensive: a response with no payload shouldn't raise an AttributeError."""
    client = FakeClient(FakeResponse(parsed=None))

    result = suggest_care_tasks(dog_with_dysplasia(), client=client, chunks=CHUNKS)

    assert result.available is False
    assert "could not be read" in result.reason


def test_a_wrongly_typed_payload_is_rejected():
    """JSON mode can return something the schema didn't produce; don't trust it."""
    client = FakeClient(FakeResponse(parsed={"suggestions": []}))

    result = suggest_care_tasks(dog_with_dysplasia(), client=client, chunks=CHUNKS)

    assert result.available is False
    assert "could not be read" in result.reason


def test_rate_limiting_gets_its_own_advice():
    """The likeliest free-tier failure, so the message says what to do about it."""
    from google.genai import errors

    error = errors.APIError(429, {"error": {"message": "quota exceeded"}})
    client = FakeClient(error)

    result = suggest_care_tasks(dog_with_dysplasia(), client=client, chunks=CHUNKS)

    assert result.available is False
    assert "Rate limited" in result.reason


def test_a_rejected_key_is_reported_clearly():
    """A 403 means the key is the problem, not the request."""
    from google.genai import errors

    error = errors.APIError(403, {"error": {"message": "permission denied"}})
    client = FakeClient(error)

    result = suggest_care_tasks(dog_with_dysplasia(), client=client, chunks=CHUNKS)

    assert "GEMINI_API_KEY was rejected" in result.reason


def test_an_empty_batch_reports_available_with_an_explanation():
    """The model returning nothing is a valid answer, not an error."""
    result, _ = call_with([])

    assert result.available is True
    assert result.suggestions == []
    assert "No suggestions passed validation" in result.reason


# --- Feature: nothing is mutated without the owner ------------------------

def test_suggesting_never_modifies_the_pet():
    """Suggestions stay advisory, so a bad generation can't rewrite a schedule."""
    pet = dog_with_dysplasia()
    pet.add_task("Morning walk", 30, PRIORITY_VALUES["high"])
    before = list(pet.tasks)

    call_with([suggested()], pet=pet)

    assert pet.tasks == before


def test_validate_batch_is_usable_on_its_own():
    """Validation is public so the evaluation harness can reuse it directly."""
    batch = SuggestionBatch(suggestions=[suggested(), suggested(source_chunk_id="nope")])

    accepted, rejected = validate_batch(batch, CHUNKS, dog_with_dysplasia())

    assert len(accepted) == 1
    assert len(rejected) == 1
