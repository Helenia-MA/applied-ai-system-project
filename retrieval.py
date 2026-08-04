"""Retrieval over the pet-care knowledge base (see knowledge/care_kb.md).

This is the "R" of the RAG feature. It answers one question: given a pet's
profile, which few care-guidance chunks should the model be allowed to see?

Why structured matching rather than embeddings
----------------------------------------------
The query here is not free text — it is four typed fields already on `Pet`
(species, breed, age, medical_condition). Because those values are known
exactly, relevance can be *asserted* rather than approximated by vector
similarity, and asserting is safer: "hip dysplasia" and "elbow dysplasia" sit
almost on top of each other in embedding space, so a similarity search can
surface the wrong condition and the model would then generate care tasks for a
disease the pet does not have. Matching a tagged condition on whole-phrase
boundaries cannot make that mistake.

The module is deliberately dependency-free and deterministic, which also makes
it fully testable offline — see tests/test_retrieval.py.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:  # pragma: no cover - import only for type checkers
    # Imported lazily so pawpal_system can use retrieval without a circular import.
    from pawpal_system import Pet


logger = logging.getLogger(__name__)

# Where the knowledge base lives, and the line that separates chunks inside it.
DEFAULT_KB_PATH = Path(__file__).parent / "knowledge" / "care_kb.md"
CHUNK_DELIMITER = "<!--CHUNK-->"

# The delimiter only counts when it is alone on its own line. Anchoring matters:
# the knowledge base documents its own format, so the delimiter also appears
# mid-sentence in that prose. Splitting on the bare string would turn the
# documentation into a bogus chunk.
_DELIMITER_PATTERN = re.compile(rf"^[ \t]*{re.escape(CHUNK_DELIMITER)}[ \t]*$", re.MULTILINE)

# How many chunks a single query may return. Sized so a fully-specified pet
# (condition + breed + age band) still gets all of its species' baseline advice
# alongside the specific chunks, rather than having feeding or dental care
# truncated off the end.
MAX_CHUNKS = 8

# Relevance weights. These are ordered by how specific the match is, so a
# condition chunk always outranks a breed chunk, which always outranks generic
# advice. The gaps are wide so no amount of keyword overlap can reorder them.
SCORE_CONDITION = 100
SCORE_BREED = 10
SCORE_AGE = 5
SCORE_GENERAL = 1

# Header keys whose values are comma-separated lists rather than single values.
_LIST_KEYS = frozenset({"species", "breeds", "conditions", "avoid"})


class KnowledgeBaseError(Exception):
    """Raised when the knowledge base cannot be read or contains no chunks.

    A separate exception type so callers can degrade gracefully (disable
    suggestions, keep scheduling) instead of crashing the whole app.
    """


@dataclass(frozen=True)
class Chunk:
    """One retrievable unit of care guidance.

    Frozen because chunks are parsed once and shared across requests — nothing
    downstream should be able to mutate the knowledge base in memory.

    `avoid` is carried through even though retrieval never filters on it: it is
    what lets the scheduler flag a planned task that this pet shouldn't do.
    """

    id: str
    text: str
    species: tuple[str, ...] = ()
    breeds: tuple[str, ...] = ()
    conditions: tuple[str, ...] = ()
    age_min: int | None = None
    age_max: int | None = None
    avoid: tuple[str, ...] = ()
    always: bool = False


# --- Normalisation helpers -----------------------------------------------

def _normalize(value: str) -> str:
    """Lowercase and collapse whitespace so matching ignores formatting.

    Applied to both sides of every comparison, so "Hip  Dysplasia" typed in the
    UI matches the `hip dysplasia` tag in the file.
    """
    return " ".join(value.lower().split())


def _split_list(value: str) -> tuple[str, ...]:
    """Parse a comma-separated header value, dropping empties."""
    return tuple(_normalize(part) for part in value.split(",") if part.strip())


def _phrase_in(phrase: str, text: str) -> bool:
    """Whether `phrase` appears in `text` as a whole phrase.

    Word boundaries are what make condition tags safe. Plain substring matching
    would let a `stairs` tag match "upstairs", and a hypothetical `dysplasia`
    tag match "elbow dysplasia". Boundary matching still handles the useful
    case: the tag `hip dysplasia` matches an owner who typed "mild hip
    dysplasia".
    """
    if not phrase or not text:
        return False
    return re.search(rf"\b{re.escape(phrase)}\b", text) is not None


def _matches_any(phrases: tuple[str, ...], text: str) -> bool:
    """Whether any of `phrases` appears in `text` as a whole phrase."""
    return any(_phrase_in(phrase, text) for phrase in phrases)


# --- Parsing --------------------------------------------------------------

def _parse_chunk(raw: str) -> Chunk | None:
    """Turn one delimited block into a Chunk, or None if it is unusable.

    A malformed chunk is skipped with a warning rather than raising, so one bad
    edit to the knowledge base degrades that entry instead of taking down the
    whole feature.
    """
    lines = raw.strip().splitlines()
    if not lines:
        return None

    # Header runs until the first blank line; everything after it is the body.
    header: dict[str, str] = {}
    body_start = len(lines)
    for index, line in enumerate(lines):
        if not line.strip():
            body_start = index + 1
            break
        key, separator, value = line.partition(":")
        if not separator:
            logger.warning("Skipping unparseable header line in KB: %r", line)
            continue
        header[_normalize(key)] = value.strip()

    body = "\n".join(lines[body_start:]).strip()

    chunk_id = _normalize(header.get("id", ""))
    if not chunk_id:
        logger.warning("Skipping KB chunk with no id (starts %r)", raw.strip()[:60])
        return None
    if not body:
        logger.warning("Skipping KB chunk %r: no body text", chunk_id)
        return None

    def as_int(key: str) -> int | None:
        """Read an optional integer header, warning rather than raising."""
        if key not in header:
            return None
        try:
            return int(header[key])
        except ValueError:
            logger.warning("Chunk %r has non-numeric %s=%r; ignoring",
                           chunk_id, key, header[key])
            return None

    return Chunk(
        id=chunk_id,
        text=body,
        species=_split_list(header.get("species", "")),
        breeds=_split_list(header.get("breeds", "")),
        conditions=_split_list(header.get("conditions", "")),
        age_min=as_int("age_min"),
        age_max=as_int("age_max"),
        avoid=_split_list(header.get("avoid", "")),
        always=_normalize(header.get("always", "")) in {"yes", "true", "1"},
    )


def parse_kb(text: str) -> list[Chunk]:
    """Parse knowledge-base text into chunks, skipping anything malformed.

    Content before the first delimiter is the file's prose header and is
    ignored, so the knowledge base can document its own format. Duplicate ids
    keep the first occurrence — ids are cited in model output and written to
    logs, so they have to be unique.
    """
    blocks = _DELIMITER_PATTERN.split(text)[1:]  # drop the prose preamble

    chunks: list[Chunk] = []
    seen: set[str] = set()
    for block in blocks:
        chunk = _parse_chunk(block)
        if chunk is None:
            continue
        if chunk.id in seen:
            logger.warning("Duplicate KB chunk id %r; keeping the first", chunk.id)
            continue
        seen.add(chunk.id)
        chunks.append(chunk)

    return chunks


# Parsed once per path and reused: the knowledge base is static at runtime, and
# re-reading it on every suggestion would be wasted work.
_kb_cache: dict[Path, list[Chunk]] = {}


def load_kb(path: Path | None = None, *, use_cache: bool = True) -> list[Chunk]:
    """Load and parse the knowledge base.

    Raises KnowledgeBaseError if the file is missing, unreadable, or yields no
    usable chunks — an empty corpus is a setup failure worth surfacing loudly
    rather than silently producing suggestions with no grounding.
    """
    kb_path = Path(path) if path is not None else DEFAULT_KB_PATH

    if use_cache and kb_path in _kb_cache:
        return _kb_cache[kb_path]

    try:
        text = kb_path.read_text(encoding="utf-8")
    except OSError as error:
        raise KnowledgeBaseError(f"Cannot read knowledge base at {kb_path}: {error}") from error

    chunks = parse_kb(text)
    if not chunks:
        raise KnowledgeBaseError(f"Knowledge base at {kb_path} contains no usable chunks")

    logger.info("Loaded %d chunks from %s", len(chunks), kb_path)
    if use_cache:
        _kb_cache[kb_path] = chunks
    return chunks


# --- Selection ------------------------------------------------------------

def _score(
    chunk: Chunk,
    species: str,
    breed: str,
    age: int | None,
    condition: str,
) -> int | None:
    """Relevance score for one chunk, or None if it does not apply.

    A chunk applies only when *every* constraint it declares is satisfied, so a
    chunk that declares nothing but `species` is general advice that matches any
    pet of that species.

    Unknown pet fields never match a chunk that constrains them: a pet with no
    recorded age cannot be shown senior-specific advice, because we can't verify
    it applies. Being conservative here is the point — the alternative is
    guessing, and the model presents whatever it receives as grounded fact.
    """
    score = 0

    # Species gate. A chunk with no species tag is species-agnostic.
    if chunk.species:
        if not species or not _matches_any(chunk.species, species):
            return None

    if chunk.breeds:
        if not breed or not _matches_any(chunk.breeds, breed):
            return None
        score += SCORE_BREED

    if chunk.conditions:
        if not condition or not _matches_any(chunk.conditions, condition):
            return None
        score += SCORE_CONDITION

    if chunk.age_min is not None or chunk.age_max is not None:
        if age is None:
            return None
        if chunk.age_min is not None and age < chunk.age_min:
            return None
        if chunk.age_max is not None and age > chunk.age_max:
            return None
        score += SCORE_AGE

    if chunk.always:
        score += SCORE_GENERAL

    # A chunk that declared no constraints and isn't marked `always` still
    # matched everything, so treat it as general advice.
    return score if score else SCORE_GENERAL


def retrieve(
    pet: "Pet",
    *,
    chunks: list[Chunk] | None = None,
    limit: int = MAX_CHUNKS,
) -> list[Chunk]:
    """Select the most relevant care chunks for one pet, most specific first.

    Ordering is by specificity (condition, then breed, then age band, then
    general advice), with chunk id as a final tiebreak so the same pet always
    produces the same context — reproducibility matters when the output feeds a
    model call you want to be able to explain.

    Returns an empty list when nothing matches, which happens mainly when a pet
    has no species recorded. Callers should treat that as "no grounding
    available" and skip the model call rather than asking it to invent advice.

    `chunks` can be passed in to retrieve against a different corpus; tests use
    it to run against small inline knowledge bases.
    """
    corpus = chunks if chunks is not None else load_kb()

    species = _normalize(pet.species or "")
    breed = _normalize(pet.breed or "")
    condition = _normalize(pet.medical_condition or "")
    age = pet.age

    scored: list[tuple[int, Chunk]] = []
    for chunk in corpus:
        score = _score(chunk, species, breed, age, condition)
        if score is not None:
            scored.append((score, chunk))

    scored.sort(key=lambda pair: (-pair[0], pair[1].id))
    selected = [chunk for _, chunk in scored[:limit]]

    # Logged at info because this line is the audit trail for the whole feature:
    # it records exactly which knowledge the model was given for which pet.
    logger.info(
        "Retrieved %d/%d chunks for %s (species=%r breed=%r age=%r condition=%r): %s",
        len(selected), len(scored), pet.name, species, breed, age, condition,
        ", ".join(chunk.id for chunk in selected) or "none",
    )
    return selected


def avoid_keywords(chunks: list[Chunk]) -> list[str]:
    """Collect the deduplicated `avoid` keywords across the given chunks.

    Used by conflict detection to flag a scheduled task that this pet's profile
    says it shouldn't do. Sorted for stable output.
    """
    return sorted({keyword for chunk in chunks for keyword in chunk.avoid})
