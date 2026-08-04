"""PawPal+ testing ground.

Run with:  python main.py

Builds a small owner/pets/tasks scenario and prints today's schedule for each
pet to the terminal, along with the scheduler's reasoning.
"""

import os
from datetime import date

from advisor import llm_enabled, suggest_care_tasks, unavailable_reason
from logging_setup import setup_logging
from pawpal_system import Owner, Scheduler, PRIORITY_VALUES, PRIORITY_LABELS
from retrieval import KnowledgeBaseError, avoid_keywords, retrieve

# Shorthand so we can read tasks as high/medium/low instead of 3/2/1.
HIGH = PRIORITY_VALUES["high"]
MEDIUM = PRIORITY_VALUES["medium"]
LOW = PRIORITY_VALUES["low"]


def build_sample_owner() -> Owner:
    """Create one owner with two pets and a handful of tasks each."""
    owner = Owner("Jordan")

    # Two pets, each with its own daily time budget.
    biscuit = owner.add_pet("Biscuit", "dog", available_minutes=60)
    mochi = owner.add_pet("Mochi", "cat", available_minutes=30)

    # Tasks added deliberately OUT OF ORDER (neither by time nor duration) so the
    # sorting/filtering demo below has something real to reorder.
    biscuit.add_task("Brushing", 25, LOW, time="19:00")    # likely won't fit the 60 min budget
    biscuit.add_task("Morning walk", 30, HIGH, time="08:00")
    biscuit.add_task("Medication", 10, HIGH, time="07:30")

    mochi.add_task("Play time", 20, LOW, time="18:30")     # likely won't fit the 30 min budget
    # Feeding is deliberately at 08:00 — the SAME time as Biscuit's "Morning walk"
    # above — so the Scheduler's time-conflict check has a cross-pet clash to catch.
    mochi.add_task("Feeding", 10, HIGH, time="08:00")
    mochi.add_task("Litter change", 15, MEDIUM, time="13:00")

    return owner


def show_task(task) -> str:
    """One-line task summary used by the demos below."""
    status = "done" if task.completed else "todo"
    label = PRIORITY_LABELS[task.priority]
    return (
        f"{task.time}  {task.name:<16} {task.duration_minutes:>3} min "
        f"[{label:<6}] ({status})"
    )


def demo_sorting_and_filtering(owner: Owner) -> None:
    """Prove the Scheduler's sorting + filtering helpers work on jumbled input."""
    scheduler = Scheduler()
    biscuit = owner.pets[0]

    print("\n" + "=" * 48)
    print(f"Sorting & filtering demo — {biscuit.name}")
    print("=" * 48)

    print("\nAs added (deliberately out of order):")
    for t in biscuit.tasks:
        print(f"  {show_task(t)}")

    print("\nSorted by time — sort_by_time():")
    for t in scheduler.sort_by_time(biscuit.tasks):
        print(f"  {show_task(t)}")

    print("\nSorted by duration, shortest first — sort_by_duration():")
    for t in scheduler.sort_by_duration(biscuit.tasks):
        print(f"  {show_task(t)}")

    # Mark one task done, then split by status to show filter_by_status().
    biscuit.tasks[0].mark_complete()
    print("\nPending only — filter_by_status(completed=False):")
    for t in scheduler.filter_by_status(biscuit.tasks, completed=False):
        print(f"  {show_task(t)}")

    print("\nCompleted only — filter_by_status(completed=True):")
    for t in scheduler.filter_by_status(biscuit.tasks, completed=True):
        print(f"  {show_task(t)}")

    # Filter by pet name — Owner.tasks_for_pet().
    print("\nTasks for 'Mochi' — tasks_for_pet('Mochi'):")
    for t in owner.tasks_for_pet("Mochi"):
        print(f"  {show_task(t)}")


def demo_recurring_spawn(owner: Owner) -> None:
    """Prove that completing a recurring task spawns its next occurrence."""
    scheduler = Scheduler()
    today = date.today()
    mochi = owner.pets[1]
    feeding = next(t for t in mochi.tasks if t.name == "Feeding")  # daily task

    print("\n" + "=" * 48)
    print("Recurring-task demo — complete_task() spawns next occurrence")
    print("=" * 48)

    print(f"\nBefore: {mochi.name} has {len(mochi.tasks)} task(s).")
    new = scheduler.complete_task(mochi, feeding.id, today)
    print(f"Completed '{feeding.name}' ({feeding.frequency}).")
    print(f"After:  {mochi.name} has {len(mochi.tasks)} task(s) "
          f"(a new occurrence was spawned).")
    print(f"  new occurrence -> {show_task(new)} due {new.due_date}")
    print(f"  due today ({today})? {new.needs_doing(today)}  "
          f"— it waits for its due date.")


def print_schedule(owner: Owner) -> None:
    """Print 'Today's Schedule' for every pet, with the scheduler's reasoning."""
    scheduler = Scheduler()
    today = date.today()
    plans = scheduler.all_owner_plans(owner, today)

    print("=" * 48)
    print(f"Today's Schedule for {owner.name}")
    print("=" * 48)

    # Owner-wide time conflicts: two tasks (same pet or different pets) at once.
    time_conflicts = scheduler.detect_time_conflicts(owner, today)
    if time_conflicts:
        print("\n⚠ Time conflicts (the owner can't be in two places at once):")
        for warning in time_conflicts:
            print(f"  - {warning}")

    for pet, plan in plans.items():
        print(f"\n{pet.name} ({pet.species}) - {pet.available_minutes} min available")
        print("-" * 48)

        if plan:
            for task in plan:
                print(f"  [ ] {task.time}  {task.name:<16} {task.duration_minutes:>3} min [priority: {PRIORITY_LABELS[task.priority]}]")
        else:
            print("  (nothing scheduled today)")

        # Conflict detection: warn before the reasoning if anything clashes.
        conflicts = scheduler.detect_conflicts(pet, today)
        if conflicts:
            print()
            print("  ⚠ Conflicts:")
            for warning in conflicts:
                print(f"    - {warning}")

        # Reasoning: what was planned vs. skipped, and why.
        skipped = [t for t in pet.tasks if t not in plan]
        print()
        print(scheduler.explain(plan, skipped, pet.available_minutes))


def demo_ai_suggestions() -> None:
    """Show retrieval changing a plan: retrieve → suggest → accept → replan.

    Builds its own owner so the demos above stay independent of this one, and so
    the pet can carry the breed, age, and condition that retrieval matches on.

    Degrades in stages rather than all at once: with no knowledge base it says so
    and stops; with a knowledge base but no API key it still shows retrieval and
    the restricted-activity warnings, and skips only the generation step.
    """
    print("\n" + "=" * 48)
    print("AI care suggestions — retrieval changes the plan")
    print("=" * 48)

    owner = Owner("Jordan")
    pet = owner.add_pet(
        "Biscuit", "dog", available_minutes=45,
        breed="Labrador Retriever", age=9, medical_condition="hip dysplasia",
    )
    pet.add_task("Morning walk", 30, HIGH, time="08:00")
    # Deliberately something the care guidance says to avoid, so the
    # restricted-activity check below has a real clash to flag.
    pet.add_task("Stairs practice", 15, LOW, time="17:00")

    scheduler = Scheduler()
    today = date.today()

    print(f"\n{pet.name} — {pet.describe()}, {pet.medical_condition}")
    print(f"{pet.available_minutes} min available")

    print("\nPlan before suggestions:")
    for task in scheduler.build_plan(pet.tasks, pet.available_minutes, today):
        print(f"  {show_task(task)}")

    # Retrieval: which guidance matches this pet's profile?
    try:
        chunks = retrieve(pet)
    except KnowledgeBaseError as error:
        print(f"\nKnowledge base unavailable: {error}")
        return

    print(f"\nRetrieved {len(chunks)} guidance chunk(s):")
    for chunk in chunks:
        print(f"  - {chunk.id}")

    restricted = avoid_keywords(chunks)
    if restricted:
        print(f"\nActivities to avoid for this pet: {', '.join(restricted)}")
        for warning in scheduler.detect_restricted_tasks(pet, restricted, today):
            print(f"  ⚠ {warning}")

    if not llm_enabled():
        print(f"\n{unavailable_reason()}")
        print("Retrieval and the warnings above still work — only the suggestion")
        print("step needs a key. See the README for setup.")
        return

    result = suggest_care_tasks(pet, chunks=chunks)
    if not result.available:
        print(f"\nSuggestions unavailable: {result.reason}")
        return

    print(f"\n{len(result.suggestions)} suggestion(s), each citing its source:")
    for suggestion in result.suggestions:
        print(f"  {suggestion.time}  {suggestion.name:<32} "
              f"{suggestion.duration_minutes:>3} min "
              f"[{PRIORITY_LABELS[suggestion.priority]:<6}] "
              f"<- {suggestion.source_chunk_id}")
    if result.rejected:
        print(f"\n{len(result.rejected)} filtered out by the guardrails:")
        for reason in result.rejected:
            print(f"  - {reason}")

    # Accept the top two, the way an owner would click Accept in the UI.
    accepted = [pet.accept_suggestion(s) for s in result.suggestions[:2]]
    print(f"\nOwner accepted: {', '.join(task.name for task in accepted)}")

    print("\nPlan after accepting:")
    plan = scheduler.build_plan(pet.tasks, pet.available_minutes, today)
    for task in plan:
        print(f"  {show_task(task)}")

    # The reasoning marks which entries came from accepted guidance.
    skipped = [t for t in pet.tasks if t.needs_doing(today) and t not in plan]
    print()
    print(scheduler.explain(plan, skipped, pet.available_minutes))


if __name__ == "__main__":
    # WARNING by default so the demo output stays readable. Set
    # PAWPAL_LOG_LEVEL=INFO to see the retrieval and token-usage lines, which are
    # the audit trail for the AI feature. Either way they go to logs/pawpal.log.
    log_path = setup_logging(os.environ.get("PAWPAL_LOG_LEVEL", "WARNING"))

    owner = build_sample_owner()
    print_schedule(owner)
    demo_sorting_and_filtering(owner)
    demo_recurring_spawn(owner)
    demo_ai_suggestions()

    if log_path:
        print(f"\nFull activity log: {log_path}")
