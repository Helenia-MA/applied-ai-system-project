"""Tests for knowledge-base parsing and retrieval (retrieval.py).

These run entirely offline — no API key, no network. Retrieval is the one part
of the RAG feature that is fully deterministic, so it is also the part worth
pinning down with assertions.
"""

from pathlib import Path

import pytest

from pawpal_system import Pet
from retrieval import (
    Chunk,
    KnowledgeBaseError,
    avoid_keywords,
    load_kb,
    parse_kb,
    retrieve,
)


# A small inline corpus, so selection tests don't depend on the real file's
# contents. Written in the same format as knowledge/care_kb.md.
SAMPLE_KB = """
Prose preamble that the parser should ignore.

<!--CHUNK-->
id: dog-general
species: dog
always: yes

Walk twice daily for 20 minutes.

<!--CHUNK-->
id: cat-general
species: cat
always: yes

Scoop the litter tray daily.

<!--CHUNK-->
id: dog-senior
species: dog
age_min: 7
avoid: stairs

Two 15-minute walks beat one long one.

<!--CHUNK-->
id: dog-puppy
species: dog
age_max: 1

Short frequent outings, 10 minutes each.

<!--CHUNK-->
id: dog-hip-dysplasia
species: dog
conditions: hip dysplasia
avoid: stairs, jumping

Swimming for 15 to 20 minutes is ideal.

<!--CHUNK-->
id: dog-elbow-dysplasia
species: dog
conditions: elbow dysplasia

Limit hard-surface running.

<!--CHUNK-->
id: dog-labrador
species: dog
breeds: labrador, labrador retriever

Measure meals; 45 to 60 minutes of exercise.
"""


def sample_chunks():
    """Parse the inline corpus once per test that needs it."""
    return parse_kb(SAMPLE_KB)


# --- Feature: parsing the knowledge-base format ---------------------------

def test_parse_kb_reads_all_chunks_and_ignores_preamble():
    """parse_kb splits on the delimiter and drops the file's prose header."""
    chunks = sample_chunks()

    # Seven chunks in the sample; the preamble before the first delimiter is not one.
    assert len(chunks) == 7
    assert "dog-general" in {chunk.id for chunk in chunks}


def test_parse_kb_reads_header_fields_and_body():
    """Header keys become typed Chunk fields, and the body is the text after them."""
    chunk = next(c for c in sample_chunks() if c.id == "dog-senior")

    assert chunk.species == ("dog",)
    assert chunk.age_min == 7
    assert chunk.age_max is None
    assert chunk.avoid == ("stairs",)
    assert "15-minute" in chunk.text
    # The header lines must not leak into the text sent to the model.
    assert "age_min" not in chunk.text


def test_parse_kb_skips_malformed_chunks_instead_of_failing():
    """A chunk with no id or no body is dropped; the rest of the file still loads."""
    messy = """
<!--CHUNK-->
species: dog

Body with no id, so unusable.

<!--CHUNK-->
id: no-body-here
species: dog

<!--CHUNK-->
id: good-chunk
species: dog

This one is fine.
"""
    chunks = parse_kb(messy)

    # Only the well-formed chunk survives — one bad edit doesn't break the feature.
    assert [chunk.id for chunk in chunks] == ["good-chunk"]


def test_parse_kb_only_splits_on_a_standalone_delimiter_line():
    """An inline mention of the delimiter is prose, not a chunk boundary.

    The knowledge base documents its own format, so the delimiter string appears
    mid-sentence in that prose. Splitting on the bare string turned those
    paragraphs into a junk chunk, so the delimiter must stand alone on its line.
    """
    with_inline_mention = """
Chunks are separated by a `<!--CHUNK-->` line, as described here.

<!--CHUNK-->
id: real-chunk
species: dog

The only actual chunk.
"""
    chunks = parse_kb(with_inline_mention)

    assert [chunk.id for chunk in chunks] == ["real-chunk"]


def test_parse_kb_keeps_first_of_duplicate_ids():
    """Ids are cited in output and logs, so duplicates collapse to the first."""
    duplicated = """
<!--CHUNK-->
id: repeated
species: dog

First version.

<!--CHUNK-->
id: repeated
species: dog

Second version.
"""
    chunks = parse_kb(duplicated)

    assert len(chunks) == 1
    assert "First" in chunks[0].text


# --- Feature: loading the real knowledge base -----------------------------

def test_load_kb_reads_the_shipped_knowledge_base():
    """The real knowledge base parses, and every chunk has an id and body."""
    chunks = load_kb()

    assert len(chunks) > 20  # the shipped corpus, not a stub
    assert all(chunk.id and chunk.text for chunk in chunks)
    # Ids must be unique, since they're the citation handle.
    assert len({chunk.id for chunk in chunks}) == len(chunks)


def test_load_kb_raises_a_clear_error_when_the_file_is_missing():
    """A missing knowledge base is a setup failure, surfaced as a typed error."""
    with pytest.raises(KnowledgeBaseError):
        load_kb(Path("knowledge/does_not_exist.md"), use_cache=False)


# --- Feature: retrieval by species ----------------------------------------

def test_retrieve_excludes_other_species():
    """A dog never receives cat guidance."""
    dog = Pet("Biscuit", "dog")

    ids = {chunk.id for chunk in retrieve(dog, chunks=sample_chunks())}

    assert "dog-general" in ids
    assert "cat-general" not in ids


def test_retrieve_returns_general_advice_for_a_bare_profile():
    """A pet with only a species still gets baseline advice, never an empty list.

    This matters because an empty retrieval means the model has no grounding,
    and the caller has to skip the suggestion entirely.
    """
    dog = Pet("Biscuit", "dog")

    chunks = retrieve(dog, chunks=sample_chunks())

    assert [chunk.id for chunk in chunks] == ["dog-general"]


def test_retrieve_returns_nothing_when_species_is_unknown():
    """With no species recorded there is nothing safe to retrieve."""
    unknown = Pet("Mystery")

    assert retrieve(unknown, chunks=sample_chunks()) == []


# --- Feature: retrieval by medical condition ------------------------------

def test_retrieve_matches_the_recorded_condition():
    """A condition chunk is selected when the pet's condition matches its tag."""
    dog = Pet("Biscuit", "dog", medical_condition="hip dysplasia")

    ids = [chunk.id for chunk in retrieve(dog, chunks=sample_chunks())]

    assert "dog-hip-dysplasia" in ids
    # Condition advice is the most specific match, so it comes first.
    assert ids[0] == "dog-hip-dysplasia"


def test_retrieve_does_not_confuse_similar_conditions():
    """The whole point of tag matching: a near-identical condition never matches.

    'elbow dysplasia' and 'hip dysplasia' are nearly the same string (and nearly
    the same vector), but they call for different care. Retrieving the wrong one
    would have the model generate tasks for a disease the pet doesn't have.
    """
    dog = Pet("Biscuit", "dog", medical_condition="elbow dysplasia")

    ids = {chunk.id for chunk in retrieve(dog, chunks=sample_chunks())}

    assert "dog-elbow-dysplasia" in ids
    assert "dog-hip-dysplasia" not in ids


def test_retrieve_matches_a_condition_inside_a_longer_description():
    """Owners type freely, so a tag matches when it appears as a whole phrase."""
    dog = Pet("Biscuit", "dog", medical_condition="Mild hip dysplasia, left side")

    ids = {chunk.id for chunk in retrieve(dog, chunks=sample_chunks())}

    assert "dog-hip-dysplasia" in ids


def test_retrieve_ignores_condition_chunks_when_no_condition_is_recorded():
    """No recorded condition means no condition-specific advice."""
    dog = Pet("Biscuit", "dog")

    ids = {chunk.id for chunk in retrieve(dog, chunks=sample_chunks())}

    assert "dog-hip-dysplasia" not in ids


# --- Feature: retrieval by age band and breed -----------------------------

def test_retrieve_respects_age_bands():
    """A senior dog gets senior advice; a puppy gets puppy advice, not both."""
    senior = Pet("Rex", "dog", age=9)
    puppy = Pet("Nib", "dog", age=1)

    senior_ids = {chunk.id for chunk in retrieve(senior, chunks=sample_chunks())}
    puppy_ids = {chunk.id for chunk in retrieve(puppy, chunks=sample_chunks())}

    assert "dog-senior" in senior_ids and "dog-puppy" not in senior_ids
    assert "dog-puppy" in puppy_ids and "dog-senior" not in puppy_ids


def test_retrieve_skips_age_banded_chunks_when_age_is_unknown():
    """An unverifiable constraint is treated as unmatched, not assumed true."""
    dog = Pet("Biscuit", "dog")  # age defaults to None

    ids = {chunk.id for chunk in retrieve(dog, chunks=sample_chunks())}

    assert "dog-senior" not in ids
    assert "dog-puppy" not in ids


def test_retrieve_matches_breed_within_a_fuller_breed_name():
    """'labrador' tag matches a pet recorded as 'Labrador Retriever'."""
    dog = Pet("Biscuit", "dog", breed="Labrador Retriever")

    ids = {chunk.id for chunk in retrieve(dog, chunks=sample_chunks())}

    assert "dog-labrador" in ids


# --- Feature: ranking, limits, and determinism ----------------------------

def test_retrieve_ranks_specific_advice_above_general_advice():
    """Condition beats breed, breed beats age band, all beat general advice."""
    dog = Pet("Biscuit", "dog", breed="labrador", age=9,
              medical_condition="hip dysplasia")

    ids = [chunk.id for chunk in retrieve(dog, chunks=sample_chunks())]

    assert ids == ["dog-hip-dysplasia", "dog-labrador", "dog-senior", "dog-general"]


def test_retrieve_respects_the_limit_and_drops_the_least_specific():
    """When more chunks match than fit, general advice is what gets cut."""
    dog = Pet("Biscuit", "dog", breed="labrador", age=9,
              medical_condition="hip dysplasia")

    ids = [chunk.id for chunk in retrieve(dog, chunks=sample_chunks(), limit=2)]

    assert ids == ["dog-hip-dysplasia", "dog-labrador"]


def test_retrieve_is_deterministic():
    """The same pet must always produce the same context for the same corpus."""
    dog = Pet("Biscuit", "dog", breed="labrador", age=9,
              medical_condition="hip dysplasia")
    corpus = sample_chunks()

    first = [chunk.id for chunk in retrieve(dog, chunks=corpus)]
    second = [chunk.id for chunk in retrieve(dog, chunks=corpus)]

    assert first == second


# --- Feature: avoid keywords for conflict detection -----------------------

def test_avoid_keywords_merges_and_deduplicates():
    """Avoid lists from several chunks combine into one sorted, unique list."""
    chunks = [
        Chunk(id="a", text="...", avoid=("stairs", "jumping")),
        Chunk(id="b", text="...", avoid=("stairs", "heat")),
    ]

    assert avoid_keywords(chunks) == ["heat", "jumping", "stairs"]


def test_avoid_keywords_is_empty_when_no_chunk_declares_one():
    """General advice carries no restrictions, so nothing is flagged."""
    assert avoid_keywords([Chunk(id="a", text="...")]) == []
