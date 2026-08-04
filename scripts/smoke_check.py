"""Live check that the care-suggestion feature works end to end.

Makes ONE real API call. The unit tests cover everything else with a fake
client, but the actual request shape only gets exercised here — so run this
after changing the model, the prompt, or the output schema.

    python scripts/smoke_check.py

Deliberately not named test_*.py or *_test.py, so pytest never collects it and
the test suite stays offline.

Exit codes: 0 if the call worked, 1 if it didn't.
"""

import logging
import os
import sys
from pathlib import Path

# Make the project root importable when run as `python scripts/smoke_check.py`.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from advisor import DEFAULT_MODEL, llm_enabled, suggest_care_tasks, unavailable_reason
from pawpal_system import PRIORITY_LABELS, Owner


def build_test_pet():
    """A pet specified well enough to pull condition, breed, and age chunks."""
    owner = Owner("Smoke Test")
    pet = owner.add_pet(
        "Biscuit", "dog",
        available_minutes=60,
        breed="Labrador Retriever",
        age=9,
        medical_condition="mild hip dysplasia",
    )
    # An existing task, so the duplicate guardrail has something to work against.
    pet.add_task("Morning walk", 30, 3, time="08:00")
    return pet


def main() -> int:
    # INFO shows the retrieval line and token usage, which is most of the point.
    logging.basicConfig(level=logging.INFO, format="  %(levelname)-7s %(name)s: %(message)s")

    if not llm_enabled():
        print(f"\nCannot run: {unavailable_reason()}")
        print("\nGet a free key from https://aistudio.google.com/ then either:")
        print("  cp .env.example .env    # and paste the key into it")
        print("or export it for this shell:")
        print("  export GEMINI_API_KEY='...'")
        return 1

    pet = build_test_pet()
    print(f"\nAsking for suggestions for {pet.name} "
          f"({pet.describe()}, {pet.medical_condition})")
    print(f"Model: {os.environ.get('PAWPAL_MODEL', DEFAULT_MODEL)} "
          "(override with PAWPAL_MODEL)\n")

    result = suggest_care_tasks(pet)

    print()
    if not result.available:
        print(f"FAILED: {result.reason}")
        return 1

    print(f"Grounded in {len(result.chunk_ids)} chunks: {', '.join(result.chunk_ids)}")
    print(f"Model: {result.model}\n")

    if result.suggestions:
        print(f"{len(result.suggestions)} suggestion(s) passed validation:\n")
        for suggestion in result.suggestions:
            label = PRIORITY_LABELS[suggestion.priority]
            print(f"  {suggestion.time}  {suggestion.name}  "
                  f"({suggestion.duration_minutes} min, {label}, {suggestion.frequency})")
            print(f"          source: {suggestion.source_chunk_id}")
            print(f"          why:    {suggestion.rationale}\n")
    else:
        print(f"No suggestions passed validation. {result.reason}\n")

    if result.rejected:
        print(f"{len(result.rejected)} rejected by the guardrails:")
        for reason in result.rejected:
            print(f"  - {reason}")
        print()

    if result.usage:
        # Free tier is rate-limited rather than metered, so these are for
        # spotting a prompt that has grown unexpectedly, not for costing.
        print(f"Tokens: {result.usage}")

    # A pass means the call worked AND grounding held: every citation must be a
    # chunk retrieval actually returned.
    ungrounded = [s.name for s in result.suggestions
                  if s.source_chunk_id not in result.chunk_ids]
    if ungrounded:
        print(f"\nFAILED: suggestions cite chunks that weren't retrieved: {ungrounded}")
        return 1

    print("\nOK — retrieval fed generation, and every citation checks out.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
