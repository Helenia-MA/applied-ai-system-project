"""Tests for PawPal+ core behaviors."""

from datetime import date, timedelta
from types import SimpleNamespace

from pawpal_system import (
    SOURCE_OWNER,
    SOURCE_SUGGESTED,
    Owner,
    Pet,
    Scheduler,
    Task,
)


def test_mark_complete_changes_status():
    """Task Completion: mark_complete() flips the task from not-done to done."""
    task = Task(id=1, name="Walk", duration_minutes=30, priority=3)

    # A new task starts incomplete...
    assert task.completed is False

    task.mark_complete()

    # ...and mark_complete() sets it to done.
    assert task.completed is True


def test_add_task_increases_pet_task_count():
    """Task Addition: adding a task to a Pet grows that pet's task list by one."""
    pet = Pet("Biscuit", "dog", available_minutes=60)

    # No tasks to start.
    assert len(pet.tasks) == 0

    pet.add_task("Morning walk", 30, 3)

    # One task after adding.
    assert len(pet.tasks) == 1


# --- Feature: sorting by time ("HH:MM") ----------------------------------

def test_sort_by_time_orders_chronologically():
    """sort_by_time orders tasks by their HH:MM clock time, earliest first."""
    pet = Pet("Biscuit", "dog", available_minutes=120)
    pet.add_task("Evening walk", 20, 1, time="18:45")
    pet.add_task("Morning meds", 10, 3, time="07:30")
    pet.add_task("Midday brush", 15, 2, time="13:00")

    ordered = Scheduler().sort_by_time(pet.tasks)

    assert [t.time for t in ordered] == ["07:30", "13:00", "18:45"]


def test_build_plan_delivers_tasks_in_time_order():
    """The plan itself comes back chronological by clock time."""
    pet = Pet("Biscuit", "dog", available_minutes=120)
    pet.add_task("Evening walk", 20, 1, time="18:45")
    pet.add_task("Morning meds", 10, 3, time="07:30")
    pet.add_task("Midday brush", 15, 2, time="13:00")

    plan = Scheduler().build_plan(pet.tasks, pet.available_minutes, date(2026, 7, 7))

    assert [t.name for t in plan] == ["Morning meds", "Midday brush", "Evening walk"]


# --- Feature: filtering by pet / status ----------------------------------

def test_tasks_for_pet_filters_by_pet():
    """Owner.tasks_for_pet returns only the named pet's tasks."""
    owner = Owner("Jordan")
    dog = owner.add_pet("Biscuit", "dog", 60)
    cat = owner.add_pet("Mochi", "cat", 30)
    dog.add_task("Walk", 30, 3)
    cat.add_task("Feeding", 10, 3)

    assert [t.name for t in owner.tasks_for_pet("Mochi")] == ["Feeding"]
    assert owner.tasks_for_pet("Nobody") == []


def test_filter_by_status_splits_done_and_pending():
    """filter_by_status separates completed from pending tasks."""
    pet = Pet("Biscuit", "dog", 60)
    done = pet.add_task("Walk", 30, 3)
    pending = pet.add_task("Brush", 15, 1)
    done.mark_complete()

    scheduler = Scheduler()
    assert scheduler.filter_by_status(pet.tasks, completed=True) == [done]
    assert scheduler.filter_by_status(pet.tasks, completed=False) == [pending]


# --- Feature: recurring tasks (spawn a new occurrence on completion) ------

def test_needs_doing_respects_due_date_and_completion():
    """Undated tasks are always due; a future due_date waits; done never needs doing."""
    today = date(2026, 7, 7)

    undated = Task(id=1, name="Walk", duration_minutes=30, priority=3)
    assert undated.needs_doing(today) is True          # no due_date -> due any day

    future = Task(id=2, name="Bath", duration_minutes=20, priority=2,
                  due_date=today + timedelta(days=1))
    assert future.needs_doing(today) is False          # not due until tomorrow
    assert future.needs_doing(today + timedelta(days=1)) is True

    undated.mark_complete()
    assert undated.needs_doing(today) is False          # completed -> not due


def test_complete_task_spawns_next_daily_occurrence():
    """Completing a daily task creates a new occurrence due tomorrow."""
    today = date(2026, 7, 7)
    pet = Pet("Biscuit", "dog", available_minutes=60)
    walk = pet.add_task("Walk", 30, 3, frequency="daily", time="08:00")

    new = Scheduler().complete_task(pet, walk.id, today)

    # Original stays as completed history; a second task now exists.
    assert walk.completed is True
    assert len(pet.tasks) == 2
    # The spawned occurrence is a distinct, not-completed task due tomorrow.
    assert new is not None and new.id != walk.id
    assert new.completed is False
    assert new.due_date == today + timedelta(days=1)
    # It carries the same details as the original.
    assert (new.name, new.duration_minutes, new.priority, new.time) == \
           ("Walk", 30, 3, "08:00")


def test_complete_task_spawns_next_weekly_occurrence():
    """Completing a weekly task creates a new occurrence due in 7 days."""
    today = date(2026, 7, 7)
    pet = Pet("Mochi", "cat", available_minutes=60)
    bath = pet.add_task("Bath", 20, 2, frequency="weekly")

    new = Scheduler().complete_task(pet, bath.id, today)

    assert new is not None
    assert new.due_date == today + timedelta(days=7)


def test_complete_task_does_not_spawn_for_one_off():
    """A non-recurring ('once') task is completed but spawns nothing."""
    today = date(2026, 7, 7)
    pet = Pet("Biscuit", "dog", available_minutes=60)
    vet = pet.add_task("Vet visit", 45, 3, frequency="once")

    new = Scheduler().complete_task(pet, vet.id, today)

    assert new is None
    assert vet.completed is True
    assert len(pet.tasks) == 1  # no new occurrence created


def test_spawned_occurrence_waits_for_its_due_date_in_the_plan():
    """The spawned occurrence is skipped today but appears on its due date."""
    today = date(2026, 7, 7)
    pet = Pet("Biscuit", "dog", available_minutes=60)
    walk = pet.add_task("Walk", 30, 3, frequency="daily", time="08:00")
    scheduler = Scheduler()

    scheduler.complete_task(pet, walk.id, today)

    # Today: original is done, next occurrence isn't due yet -> nothing planned.
    assert scheduler.build_plan(pet.tasks, pet.available_minutes, today) == []
    # Tomorrow: the spawned occurrence is due and gets planned.
    tomorrow = today + timedelta(days=1)
    plan = scheduler.build_plan(pet.tasks, pet.available_minutes, tomorrow)
    assert [t.name for t in plan] == ["Walk"]


# --- Feature: basic conflict detection -----------------------------------

def test_detect_conflicts_flags_over_budget():
    """When due tasks exceed available time, a conflict is reported."""
    pet = Pet("Biscuit", "dog", available_minutes=30)
    pet.add_task("Walk", 30, 3)
    pet.add_task("Brush", 15, 1)  # 45 min total > 30 available

    conflicts = Scheduler().detect_conflicts(pet, date(2026, 7, 7))

    assert any("Over budget" in c for c in conflicts)


def test_detect_conflicts_flags_duplicates():
    """Adding the same task name twice is flagged as a duplicate."""
    pet = Pet("Biscuit", "dog", available_minutes=120)
    pet.add_task("Walk", 30, 3)
    pet.add_task("walk", 30, 3)  # same name, different case

    conflicts = Scheduler().detect_conflicts(pet, date(2026, 7, 7))

    assert any("Duplicate" in c for c in conflicts)


def test_no_conflicts_when_everything_fits():
    """A pet whose due tasks fit its budget reports no conflicts."""
    pet = Pet("Mochi", "cat", available_minutes=60)
    pet.add_task("Feeding", 10, 3)
    pet.add_task("Litter", 15, 2)

    assert Scheduler().detect_conflicts(pet, date(2026, 7, 7)) == []


# --- Feature: same-time conflict detection (Step 4) ----------------------

def test_detect_time_conflicts_across_different_pets():
    """Two pets with tasks at the same clock time are flagged (owner-wide)."""
    today = date(2026, 7, 7)
    owner = Owner("Jordan")
    dog = owner.add_pet("Biscuit", "dog", 120)
    cat = owner.add_pet("Mochi", "cat", 120)
    dog.add_task("Walk", 30, 3, time="08:00")
    cat.add_task("Feeding", 10, 3, time="08:00")

    warnings = Scheduler().detect_time_conflicts(owner, today)

    assert len(warnings) == 1
    assert "08:00" in warnings[0]
    assert "Biscuit's Walk" in warnings[0]
    assert "Mochi's Feeding" in warnings[0]


def test_detect_time_conflicts_within_one_pet():
    """Two tasks on the SAME pet at the same time are also flagged."""
    today = date(2026, 7, 7)
    owner = Owner("Jordan")
    dog = owner.add_pet("Biscuit", "dog", 120)
    dog.add_task("Walk", 30, 3, time="08:00")
    dog.add_task("Meds", 10, 3, time="08:00")

    warnings = Scheduler().detect_time_conflicts(owner, today)

    assert len(warnings) == 1
    assert "08:00" in warnings[0]


def test_no_time_conflict_when_times_differ():
    """Distinct times produce no warning."""
    today = date(2026, 7, 7)
    owner = Owner("Jordan")
    dog = owner.add_pet("Biscuit", "dog", 120)
    dog.add_task("Walk", 30, 3, time="08:00")
    dog.add_task("Meds", 10, 3, time="09:00")

    assert Scheduler().detect_time_conflicts(owner, today) == []


def test_completed_task_does_not_cause_false_time_conflict():
    """A completed occurrence at a slot doesn't clash with a pending one."""
    today = date(2026, 7, 7)
    owner = Owner("Jordan")
    dog = owner.add_pet("Biscuit", "dog", 120)
    done = dog.add_task("Walk", 30, 3, time="08:00")
    dog.add_task("Meds", 10, 3, time="08:00")
    done.mark_complete()  # no longer due -> excluded from the clash check

    assert Scheduler().detect_time_conflicts(owner, today) == []


# --- Feature: greedy plan selection (the core scheduling algorithm) -------

def test_build_plan_skips_task_that_does_not_fit_but_keeps_going():
    """'Skip and keep going': a task too big for the leftover time is skipped,
    yet a shorter, lower-priority task still slots into the remaining minutes."""
    today = date(2026, 7, 7)
    pet = Pet("Biscuit", "dog", available_minutes=40)
    # High priority first (25 min), then another high that WON'T fit (30 min),
    # then a low 15-min task that fits in the leftover 15 min.
    pet.add_task("Walk", 25, 3, time="08:00")
    pet.add_task("Training", 30, 3, time="09:00")   # 25 + 30 = 55 > 40 -> skipped
    pet.add_task("Brush", 15, 1, time="10:00")      # 25 + 15 = 40 -> fits exactly

    plan = Scheduler().build_plan(pet.tasks, pet.available_minutes, today)

    names = [t.name for t in plan]
    assert "Walk" in names           # highest priority, taken first
    assert "Training" not in names   # didn't fit -> skipped
    assert "Brush" in names          # shorter task fills leftover time
    # Delivered chronologically.
    assert names == ["Walk", "Brush"]


def test_build_plan_breaks_priority_ties_by_shorter_duration():
    """Among equal-priority tasks, the shorter one is chosen when only one fits."""
    today = date(2026, 7, 7)
    pet = Pet("Biscuit", "dog", available_minutes=15)
    pet.add_task("Long walk", 30, 3, time="08:00")   # same priority, too long
    pet.add_task("Quick meds", 10, 3, time="09:00")  # same priority, fits

    plan = Scheduler().build_plan(pet.tasks, pet.available_minutes, today)

    assert [t.name for t in plan] == ["Quick meds"]


def test_build_plan_includes_task_that_exactly_fills_budget():
    """Boundary: a task whose duration equals the remaining minutes is included."""
    today = date(2026, 7, 7)
    pet = Pet("Biscuit", "dog", available_minutes=30)
    pet.add_task("Walk", 30, 3, time="08:00")  # exactly 30 of 30 min

    plan = Scheduler().build_plan(pet.tasks, pet.available_minutes, today)

    assert [t.name for t in plan] == ["Walk"]


def test_build_plan_empty_for_pet_with_no_tasks():
    """Edge case: a pet with no tasks plans to an empty list without error."""
    today = date(2026, 7, 7)
    pet = Pet("Biscuit", "dog", available_minutes=60)

    assert Scheduler().build_plan(pet.tasks, pet.available_minutes, today) == []


def test_build_plan_empty_when_zero_minutes_available():
    """A zero-minute budget schedules nothing, even with due tasks."""
    today = date(2026, 7, 7)
    pet = Pet("Biscuit", "dog", available_minutes=0)
    pet.add_task("Walk", 10, 3, time="08:00")

    assert Scheduler().build_plan(pet.tasks, pet.available_minutes, today) == []


# --- Feature: pet profile (breed / age / medical condition) --------------

def test_add_pet_stores_profile_fields():
    """Owner.add_pet passes breed, age, and medical condition through to the Pet."""
    owner = Owner("Jordan")

    pet = owner.add_pet(
        "Biscuit", "dog", 60,
        breed="labrador", age=3, medical_condition="arthritis",
    )

    assert (pet.breed, pet.age, pet.medical_condition) == ("labrador", 3, "arthritis")


def test_pet_profile_fields_are_optional():
    """A pet added without profile details has no breed, age, or condition."""
    pet = Pet("Mochi", "cat", available_minutes=30)

    assert pet.breed == ""
    # None (not 0 / "") so "unknown" stays distinct from a real value.
    assert pet.age is None
    assert pet.medical_condition is None


def test_describe_joins_filled_fields_and_skips_blanks():
    """describe() lists only the profile fields that were actually given."""
    full = Pet("Biscuit", "dog", 60, breed="labrador", age=3)
    one_year_old = Pet("Pip", "hamster", 10, age=1)
    bare = Pet("Nameless")

    assert full.describe() == "dog · labrador · 3 yrs"
    assert one_year_old.describe() == "hamster · 1 yr"   # singular for one year
    assert bare.describe() == ""


# --- Feature: reasoning / explanation ------------------------------------

def test_explain_reports_planned_and_skipped_counts():
    """explain() summarizes how many tasks fit, the minutes used, and what was skipped."""
    pet = Pet("Biscuit", "dog", available_minutes=30)
    walk = pet.add_task("Walk", 30, 3, time="08:00")
    brush = pet.add_task("Brush", 15, 1, time="09:00")

    scheduler = Scheduler()
    text = scheduler.explain(planned=[walk], skipped=[brush], available_minutes=30)

    assert "Planned 1 of 2 task(s)" in text
    assert "30 of 30 min used" in text
    assert "Walk" in text and "Brush" in text
    assert "didn't fit remaining time" in text


# --- Feature: task provenance (owner vs accepted AI suggestion) ----------

def test_tasks_are_owner_sourced_by_default():
    """Provenance defaults to the owner, so existing behaviour is unchanged."""
    pet = Pet("Biscuit", "dog", available_minutes=60)

    task = pet.add_task("Morning walk", 30, 3)

    assert task.source == SOURCE_OWNER
    assert task.source_note == ""


def test_accept_suggestion_creates_a_real_task():
    """An accepted suggestion becomes an ordinary Task tagged with its origin."""
    pet = Pet("Biscuit", "dog", available_minutes=60)
    suggestion = SimpleNamespace(
        name="Swim session", duration_minutes=20, priority=3,
        time="09:00", frequency="daily", source_chunk_id="dog-hip-dysplasia",
    )

    task = pet.accept_suggestion(suggestion)

    assert task in pet.tasks
    assert task.name == "Swim session"
    assert task.duration_minutes == 20
    assert task.time == "09:00"
    # Tagged so the owner can always tell which tasks came from a suggestion,
    # and which piece of guidance produced this one.
    assert task.source == SOURCE_SUGGESTED
    assert task.source_note == "dog-hip-dysplasia"


def test_accepted_suggestions_get_their_own_ids():
    """Suggested tasks share the pet's id counter, so ids stay unique."""
    pet = Pet("Biscuit", "dog", available_minutes=60)
    owner_task = pet.add_task("Morning walk", 30, 3)
    suggestion = SimpleNamespace(
        name="Swim session", duration_minutes=20, priority=3,
        time="09:00", frequency="daily", source_chunk_id="dog-hip-dysplasia",
    )

    suggested = pet.accept_suggestion(suggestion)

    assert suggested.id != owner_task.id


def test_provenance_survives_recurrence():
    """Tomorrow's occurrence of an accepted suggestion is still a suggestion."""
    pet = Pet("Biscuit", "dog", available_minutes=60)
    suggestion = SimpleNamespace(
        name="Swim session", duration_minutes=20, priority=3,
        time="09:00", frequency="daily", source_chunk_id="dog-hip-dysplasia",
    )
    accepted = pet.accept_suggestion(suggestion)

    spawned = Scheduler().complete_task(pet, accepted.id, date(2026, 7, 7))

    assert spawned.source == SOURCE_SUGGESTED
    assert spawned.source_note == "dog-hip-dysplasia"


# --- Feature: accepted suggestions change the plan -----------------------

def test_an_accepted_suggestion_competes_for_the_time_budget():
    """The integration that matters: a suggestion changes what the plan contains.

    The accepted task is high priority and fits, so it displaces a low-priority
    task that previously fit. Nothing in build_plan knows about suggestions —
    they're ordinary tasks by the time it sees them.
    """
    pet = Pet("Biscuit", "dog", available_minutes=30)
    pet.add_task("Brushing", 25, 1, time="19:00")     # low priority, fits alone
    scheduler = Scheduler()
    today = date(2026, 7, 7)

    before = [t.name for t in scheduler.build_plan(pet.tasks, 30, today)]
    assert before == ["Brushing"]

    pet.accept_suggestion(SimpleNamespace(
        name="Medication", duration_minutes=10, priority=3,
        time="07:30", frequency="daily", source_chunk_id="dog-arthritis",
    ))
    after = [t.name for t in scheduler.build_plan(pet.tasks, 30, today)]

    # Medication is high priority so it's taken first; Brushing no longer fits
    # in the 20 minutes left.
    assert after == ["Medication"]


def test_explain_marks_suggested_tasks_with_their_source():
    """The plan's reasoning shows which entries came from retrieved guidance."""
    pet = Pet("Biscuit", "dog", available_minutes=60)
    owner_task = pet.add_task("Morning walk", 30, 3, time="08:00")
    suggested = pet.accept_suggestion(SimpleNamespace(
        name="Swim session", duration_minutes=20, priority=3,
        time="09:00", frequency="daily", source_chunk_id="dog-hip-dysplasia",
    ))

    text = Scheduler().explain([owner_task, suggested], [], 60)

    assert "Swim session — 20 min [high] (suggested from dog-hip-dysplasia)" in text
    # An owner's own task is unmarked, so the common case reads as before.
    assert "Morning walk — 30 min [high]\n" in text or text.endswith(
        "Morning walk — 30 min [high]")


# --- Feature: retrieved guidance flags restricted tasks ------------------

def test_detect_restricted_tasks_flags_a_clashing_task():
    """Retrieved 'avoid' keywords change how the scheduler judges existing tasks."""
    pet = Pet("Biscuit", "dog", available_minutes=60,
              medical_condition="hip dysplasia")
    pet.add_task("Stairs practice", 15, 2, time="10:00")
    pet.add_task("Gentle swim", 20, 3, time="11:00")

    warnings = Scheduler().detect_restricted_tasks(
        pet, ["stairs", "jumping"], date(2026, 7, 7))

    assert len(warnings) == 1
    assert "Stairs practice" in warnings[0]
    assert "stairs" in warnings[0]


def test_detect_restricted_tasks_matches_whole_words_only():
    """'stairs' must not fire on 'upstairs' — the same rule retrieval tags use."""
    pet = Pet("Biscuit", "dog", available_minutes=60)
    pet.add_task("Upstairs bedroom tidy", 10, 1, time="10:00")

    warnings = Scheduler().detect_restricted_tasks(
        pet, ["stairs"], date(2026, 7, 7))

    assert warnings == []


def test_detect_restricted_tasks_warns_once_per_task():
    """A task matching two keywords is still one warning, not two."""
    pet = Pet("Biscuit", "dog", available_minutes=60)
    pet.add_task("Stairs and jumping drills", 15, 2, time="10:00")

    warnings = Scheduler().detect_restricted_tasks(
        pet, ["stairs", "jumping"], date(2026, 7, 7))

    assert len(warnings) == 1


def test_detect_restricted_tasks_ignores_completed_tasks():
    """Only tasks still due are worth warning about."""
    pet = Pet("Biscuit", "dog", available_minutes=60)
    task = pet.add_task("Stairs practice", 15, 2, time="10:00")
    task.mark_complete()

    assert Scheduler().detect_restricted_tasks(
        pet, ["stairs"], date(2026, 7, 7)) == []


def test_detect_restricted_tasks_is_empty_with_no_restrictions():
    """A pet with no retrieved restrictions gets no warnings."""
    pet = Pet("Biscuit", "dog", available_minutes=60)
    pet.add_task("Stairs practice", 15, 2, time="10:00")

    assert Scheduler().detect_restricted_tasks(pet, [], date(2026, 7, 7)) == []


def test_restricted_tasks_flags_owner_and_suggested_tasks_alike():
    """The check is about the activity, not who scheduled it."""
    pet = Pet("Biscuit", "dog", available_minutes=60)
    pet.add_task("Stairs practice", 15, 2, time="10:00")
    pet.accept_suggestion(SimpleNamespace(
        name="Jumping practice", duration_minutes=10, priority=2,
        time="11:00", frequency="daily", source_chunk_id="dog-general-enrichment",
    ))

    warnings = Scheduler().detect_restricted_tasks(
        pet, ["stairs", "jumping"], date(2026, 7, 7))

    assert len(warnings) == 2
