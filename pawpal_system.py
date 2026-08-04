"""PawPal+ — class skeleton generated from diagrams/uml.mmd.
"""

import re
from dataclasses import dataclass
from datetime import date, timedelta
from typing import TYPE_CHECKING

if TYPE_CHECKING:  # pragma: no cover - import only for type checkers
    # Type-only, so this module stays runtime-independent of the AI feature: the
    # scheduler works with no knowledge base, no API key, and no SDK installed.
    from advisor import CareSuggestion


# Priority is stored as a NUMBER internally (higher = more important) so tasks
# sort naturally. The UI translates to/from labels using these mappings.
PRIORITY_LABELS = {3: "high", 2: "medium", 1: "low"}
PRIORITY_VALUES = {label: value for value, label in PRIORITY_LABELS.items()}

# How many days must pass before a recurring task is due again.
FREQUENCY_DAYS = {"daily": 1, "weekly": 7}

# Where a task came from. Tracked so the owner can always tell which parts of a
# plan they wrote and which came from an AI suggestion they accepted — the plan
# shows both together, so provenance has to travel with the task.
SOURCE_OWNER = "owner"
SOURCE_SUGGESTED = "suggested"


def _provenance(task: "Task") -> str:
    """Reasoning-line suffix marking a task the owner accepted from a suggestion.

    Owner-created tasks get nothing, so the common case reads unchanged. Applied
    in `Scheduler.explain` so the plan's own reasoning shows which entries came
    from retrieved care guidance and which chunk each one came from.
    """
    if task.source != SOURCE_SUGGESTED:
        return ""
    return f" (suggested from {task.source_note})" if task.source_note else " (suggested)"


@dataclass
class Task:
    """A single occurrence of a pet-care task.

    Recurrence is modeled by SPAWNING: completing a daily/weekly task creates a
    fresh Task for the next occurrence (see Scheduler.complete_task), while the
    finished one stays in the list as history. `due_date` is the day this
    occurrence is for; None means "any day" (an undated one-off).
    """
    id: int
    name: str
    duration_minutes: int
    priority: int
    frequency: str = "daily"        # e.g. "daily", "weekly", or "once"
    completed: bool = False
    time: str = "12:00"             # 24-hour "HH:MM" clock time this task happens
    due_date: date | None = None    # the day this occurrence is due (None = any day)
    source: str = SOURCE_OWNER      # SOURCE_OWNER, or SOURCE_SUGGESTED if AI-proposed
    source_note: str = ""           # for suggested tasks: the guidance behind it

    def mark_complete(self) -> None:
        """Mark this occurrence as done."""
        self.completed = True

    def needs_doing(self, today: date) -> bool:
        """Whether this occurrence still needs doing on `today`.

        Done occurrences never need doing. An undated task (no `due_date`) is
        always due; a dated one is due once its `due_date` has arrived.
        """
        if self.completed:
            return False
        if self.due_date is None:
            return True
        return self.due_date <= today


class Pet:
    """A pet, its care tasks, and how much time the owner has for it today.

    Each pet manages its own tasks and carries its own available_minutes, so the
    owner can allocate time per pet (e.g. 60 min for the dog, 30 for the cat).

    Profile fields (breed, age, medical_condition) are descriptive only — they
    don't affect scheduling. `medical_condition` is optional: None means "no
    known condition", which is why it isn't just an empty string.
    """

    def __init__(
        self,
        name: str,
        species: str = "",
        available_minutes: int = 0,
        breed: str = "",
        age: int | None = None,
        medical_condition: str | None = None,
    ) -> None:
        """Create a pet with an empty task list and its own time budget."""
        self.name: str = name
        self.species: str = species
        self.available_minutes: int = available_minutes
        self.breed: str = breed
        self.age: int | None = age                             # in years; None = unknown
        self.medical_condition: str | None = medical_condition  # None = none known
        self.tasks: list[Task] = []
        # Counter so each task gets a unique, deterministic id (1, 2, 3...).
        self._next_id: int = 1

    def add_task(
        self,
        name: str,
        duration_minutes: int,
        priority: int,
        frequency: str = "daily",
        time: str = "12:00",
        due_date: date | None = None,
        source: str = SOURCE_OWNER,
        source_note: str = "",
    ) -> Task:
        """Create a Task with the next id, append it, and return it."""
        task = Task(
            self._next_id, name, duration_minutes, priority, frequency,
            time=time, due_date=due_date, source=source, source_note=source_note,
        )
        self._next_id += 1
        self.tasks.append(task)
        return task

    def accept_suggestion(self, suggestion: "CareSuggestion") -> Task:
        """Turn an accepted AI suggestion into a real task on this pet.

        This is the point where the RAG feature stops being advisory and starts
        changing the schedule: from here the task is an ordinary Task, so it goes
        through `Scheduler.build_plan` and the conflict checks like any other —
        competing for the same time budget and able to displace lower-priority
        work. Nothing about the scheduler needed to change to allow that.

        Only reachable through an explicit owner action. The task is tagged
        SOURCE_SUGGESTED and keeps the chunk id it came from, so a suggestion can
        always be traced back to the guidance that produced it.
        """
        return self.add_task(
            suggestion.name,
            suggestion.duration_minutes,
            suggestion.priority,
            frequency=suggestion.frequency,
            time=suggestion.time,
            source=SOURCE_SUGGESTED,
            source_note=suggestion.source_chunk_id,
        )

    def edit_task(
        self,
        id: int,
        name: str | None = None,
        duration_minutes: int | None = None,
        priority: int | None = None,
        frequency: str | None = None,
        completed: bool | None = None,
        time: str | None = None,
    ) -> Task:
        """Find the task with this id and update the fields that were provided."""
        for task in self.tasks:
            if task.id == id:
                if name is not None:
                    task.name = name
                if duration_minutes is not None:
                    task.duration_minutes = duration_minutes
                if priority is not None:
                    task.priority = priority
                if frequency is not None:
                    task.frequency = frequency
                if completed is not None:
                    task.completed = completed
                if time is not None:
                    task.time = time
                return task
        raise ValueError(f"No task with id {id}")

    def set_availability(self, minutes: int) -> None:
        """Set how many minutes the owner has for this pet today."""
        self.available_minutes = minutes

    def describe(self) -> str:
        """One-line profile, e.g. "dog · labrador · 3 yrs" — blank fields drop out.

        Both UI sections show a pet header, so the formatting lives here rather
        than being duplicated. Returns "" for a pet with no profile filled in.
        """
        parts = [self.species, self.breed]
        if self.age is not None:
            parts.append(f"{self.age} yr" if self.age == 1 else f"{self.age} yrs")
        return " · ".join(p for p in parts if p)


class Owner:
    """Holds the owner's pets. Time is allocated per pet (see Pet.available_minutes)."""

    def __init__(self, name: str = "") -> None:
        """Create an owner with an empty list of pets."""
        self.name: str = name
        self.pets: list[Pet] = []

    def add_pet(
        self,
        name: str,
        species: str = "",
        available_minutes: int = 0,
        breed: str = "",
        age: int | None = None,
        medical_condition: str | None = None,
    ) -> Pet:
        """Create a Pet (with its own time budget), append it, and return it."""
        pet = Pet(
            name, species, available_minutes,
            breed=breed, age=age, medical_condition=medical_condition,
        )
        self.pets.append(pet)
        return pet

    def get_all_tasks(self) -> list[Task]:
        """Return every task across all of the owner's pets, in one flat list."""
        return [task for pet in self.pets for task in pet.tasks]

    def tasks_for_pet(self, name: str) -> list[Task]:
        """Filter by pet: return the tasks of the pet with this name (empty if none)."""
        for pet in self.pets:
            if pet.name == name:
                return pet.tasks
        return []


class Scheduler:
    """Turns a list of tasks + a time budget into an ordered daily plan.

    Strategy (from the design):
      - Sort strictly by priority (high first), then shortest-duration as tie-break.
      - "Skip and keep going": if a task doesn't fit the remaining time, skip it
        and try the next, so leftover minutes aren't wasted. Greedy, not optimal.
    """

    def sort_by_duration(self, tasks: list[Task], ascending: bool = True) -> list[Task]:
        """Sort tasks by how long they take (shortest first by default)."""
        return sorted(tasks, key=lambda t: t.duration_minutes, reverse=not ascending)

    def sort_by_time(self, tasks: list[Task]) -> list[Task]:
        """Order tasks chronologically by their "HH:MM" clock time.

        Zero-padded 24-hour times sort lexicographically the same as they do
        chronologically ("07:30" < "13:00" < "18:45"), so a plain string key on
        `t.time` is all we need.
        """
        return sorted(tasks, key=lambda t: t.time)

    def filter_by_status(self, tasks: list[Task], completed: bool) -> list[Task]:
        """Filter by status: return only completed tasks, or only pending ones."""
        return [t for t in tasks if t.completed == completed]

    def build_plan(
        self,
        tasks: list[Task],
        available_minutes: int,
        today: date,
    ) -> list[Task]:
        """Choose the tasks due `today` that fit the budget, ordered for the day.

        Selection is greedy by priority (high first), shortest-duration as the
        tie-break, with "skip and keep going": a task that doesn't fit is skipped
        and we keep checking shorter ones so leftover minutes aren't wasted.
        Only tasks that `needs_doing(today)` are considered, so completed
        occurrences drop out and future spawned occurrences wait for their
        due date. The returned plan is sorted by clock time so the owner sees
        it in the order they'll actually do it.
        """
        # Keep only what's due today, then order it for greedy selection.
        due = [t for t in tasks if t.needs_doing(today)]
        ordered = sorted(due, key=lambda t: (-t.priority, t.duration_minutes))

        plan: list[Task] = []
        used = 0
        for task in ordered:
            if used + task.duration_minutes <= available_minutes:
                plan.append(task)
                used += task.duration_minutes
        # Deliver the chosen tasks in chronological order.
        return self.sort_by_time(plan)

    def all_owner_plans(self, owner: "Owner", today: date) -> dict[Pet, list[Task]]:
        """Plan every pet separately for `today`: one schedule per pet, keyed by pet."""
        return {
            pet: self.build_plan(pet.tasks, pet.available_minutes, today)
            for pet in owner.pets
        }

    def complete_task(self, pet: "Pet", task_id: int, today: date) -> "Task | None":
        """Mark a task complete and, if it recurs, spawn its next occurrence.

        The finished occurrence stays on the pet as history. For a "daily" or
        "weekly" task a NEW Task is created and appended, due `FREQUENCY_DAYS`
        days from `today`. Returns the new occurrence, or None for a one-off
        task (any frequency not in `FREQUENCY_DAYS`, e.g. "once").
        """
        task = next((t for t in pet.tasks if t.id == task_id), None)
        if task is None:
            raise ValueError(f"No task with id {task_id}")

        task.mark_complete()

        interval = FREQUENCY_DAYS.get(task.frequency)
        if interval is None:
            return None  # one-off task: nothing to reschedule
        return pet.add_task(
            task.name,
            task.duration_minutes,
            task.priority,
            frequency=task.frequency,
            time=task.time,
            due_date=today + timedelta(days=interval),
            # Provenance survives recurrence: tomorrow's occurrence of an
            # accepted suggestion is still a suggested task.
            source=task.source,
            source_note=task.source_note,
        )

    def detect_time_conflicts(self, owner: "Owner", today: date) -> list[str]:
        """Lightweight time-clash detection across ALL of an owner's pets.

        Two care tasks at the same clock time can't both be done at once (the
        owner is one person), so this groups every task due `today` by its
        `time` and returns a warning for each slot holding more than one task.
        Because it scans owner-wide, it catches clashes within a single pet AND
        across different pets. Returns warning strings (empty = no clash) and
        never raises — it warns rather than crashing.
        """
        # Map "HH:MM" -> the tasks scheduled then, labelled by pet.
        by_time: dict[str, list[str]] = {}
        for pet in owner.pets:
            for task in pet.tasks:
                if task.needs_doing(today):
                    by_time.setdefault(task.time, []).append(f"{pet.name}'s {task.name}")

        warnings: list[str] = []
        for slot in sorted(by_time):
            clashing = by_time[slot]
            if len(clashing) > 1:
                warnings.append(
                    f"Time conflict at {slot}: {', '.join(clashing)} overlap."
                )
        return warnings

    def detect_conflicts(self, pet: "Pet", today: date) -> list[str]:
        """Basic conflict detection for one pet's due tasks on `today`.

        Flags two everyday problems:
          - Over-budget: the due tasks need more time than the pet has, so some
            care won't fit (the plan will have to drop tasks).
          - Duplicates: the same task name appears more than once (likely a
            double add).
        Returns a list of human-readable warnings; empty means no conflicts.
        """
        due = [t for t in pet.tasks if t.needs_doing(today)]
        conflicts: list[str] = []

        needed = sum(t.duration_minutes for t in due)
        if needed > pet.available_minutes:
            over = needed - pet.available_minutes
            conflicts.append(
                f"Over budget: {len(due)} due task(s) need {needed} min but only "
                f"{pet.available_minutes} min available ({over} min short)."
            )

        seen: set[str] = set()
        dupes: set[str] = set()
        for t in due:
            key = t.name.lower()
            if key in seen:
                dupes.add(t.name)
            seen.add(key)
        for name in sorted(dupes):
            conflicts.append(f"Duplicate task: '{name}' is listed more than once.")

        return conflicts

    def detect_restricted_tasks(
        self,
        pet: "Pet",
        avoid: list[str],
        today: date,
    ) -> list[str]:
        """Flag due tasks that clash with what this pet should avoid.

        `avoid` is the list of activity keywords drawn from the care guidance
        retrieved for this pet (see `retrieval.avoid_keywords`). This is the
        second way the knowledge base changes system behaviour: rather than only
        adding tasks, retrieved guidance also changes how the scheduler *judges*
        the tasks already there. A dog whose profile says "avoid stairs" gets its
        existing stair-climbing task flagged, whether an owner or an AI added it.

        Keywords are matched on whole-word boundaries so "stairs" doesn't fire on
        "upstairs". Warns rather than removing anything — the owner decides, and
        a keyword match is a prompt to think, not a verdict.

        Takes `avoid` as an argument rather than fetching it, which keeps this
        module free of any runtime dependency on the knowledge base or the AI
        feature. Returns human-readable warnings; empty means nothing clashed.
        """
        warnings: list[str] = []
        for task in pet.tasks:
            if not task.needs_doing(today):
                continue
            for keyword in avoid:
                # Same whole-phrase rule retrieval uses for its tags. Duplicated
                # in three lines rather than imported, to keep this module
                # standalone.
                if re.search(rf"\b{re.escape(keyword)}\b", task.name.lower()):
                    warnings.append(
                        f"'{task.name}' involves {keyword}, which {pet.name}'s "
                        f"care profile says to avoid."
                    )
                    break  # one warning per task is enough
        return warnings

    def explain(
        self,
        planned: list[Task],
        skipped: list[Task],
        available_minutes: int,
    ) -> str:
        """Human-readable reasoning: what was planned, what was skipped and why.

        `skipped` is any task not in the plan (didn't fit, or already completed);
        each task's own `completed` flag tells us which reason to show.
        """
        used = sum(t.duration_minutes for t in planned)
        total = len(planned) + len(skipped)
        free = available_minutes - used

        lines = [
            f"Planned {len(planned)} of {total} task(s) — "
            f"{used} of {available_minutes} min used ({free} min free)."
        ]

        if planned:
            lines.append("")
            lines.append("Included:")
            for t in planned:
                label = PRIORITY_LABELS.get(t.priority, str(t.priority))
                lines.append(
                    f"  • {t.name} — {t.duration_minutes} min [{label}]{_provenance(t)}"
                )

        if skipped:
            lines.append("")
            lines.append("Skipped:")
            for t in skipped:
                label = PRIORITY_LABELS.get(t.priority, str(t.priority))
                reason = "already completed" if t.completed else "didn't fit remaining time"
                lines.append(
                    f"  • {t.name} — {t.duration_minutes} min [{label}]"
                    f"{_provenance(t)} ({reason})"
                )

        return "\n".join(lines)
