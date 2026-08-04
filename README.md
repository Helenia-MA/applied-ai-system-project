# PawPal+ (Module 2 Project)

You are building **PawPal+**, a Streamlit app that helps a pet owner plan care tasks for their pet.

## Scenario

A busy pet owner needs help staying consistent with pet care. They want an assistant that can:

- Track pet care tasks (walks, feeding, meds, enrichment, grooming, etc.)
- Consider constraints (time available, priority, owner preferences)
- Produce a daily plan and explain why it chose that plan

Your job is to design the system first (UML), then implement the logic in Python, then connect it to the Streamlit UI.

## What you will build

Your final app should:

- Let a user enter basic owner + pet info
- Let a user add/edit tasks (duration + priority at minimum)
- Generate a daily schedule/plan based on constraints and priorities
- Display the plan clearly (and ideally explain the reasoning)
- Include tests for the most important scheduling behaviors

## Getting started

### Setup

```bash
python -m venv .venv
source .venv/bin/activate  # Windows: .venv\Scripts\activate
pip install -r requirements.txt
```

### Suggested workflow

1. Read the scenario carefully and identify requirements and edge cases.
2. Draft a UML diagram (classes, attributes, methods, relationships).
3. Convert UML into Python class stubs (no logic yet).
4. Implement scheduling logic in small increments.
5. Add tests to verify key behaviors.
6. Connect your logic to the Streamlit UI in `app.py`.
7. Refine UML so it matches what you actually built.

## 🖥️ Sample Output

Paste a sample of your app's CLI or Streamlit output here so a reader can see what a generated plan looks like:

```
# e.g.:
# Daily plan for Biscuit (Golden Retriever):
#   08:00 — Morning walk (30 min) [priority: high]
#   09:00 — Feeding (10 min) [priority: high]
#   ...
```

```
# ================================================
Today's Schedule for Jordan
================================================

⚠ Time conflicts (the owner can't be in two places at once):
  - Time conflict at 08:00: Biscuit's Morning walk, Mochi's Feeding overlap.

Biscuit (dog) - 60 min available
------------------------------------------------
  [ ] 07:30  Medication        10 min [priority: high]
  [ ] 08:00  Morning walk      30 min [priority: high]

  ⚠ Conflicts:
    - Over budget: 3 due task(s) need 65 min but only 60 min available (5 min short).

Planned 2 of 3 task(s) — 40 of 60 min used (20 min free).

Included:
  • Medication — 10 min [high]
  • Morning walk — 30 min [high]

Skipped:
  • Brushing — 25 min [low] (didn't fit remaining time)

Mochi (cat) - 30 min available
------------------------------------------------
  [ ] 08:00  Feeding           10 min [priority: high]
  [ ] 13:00  Litter change     15 min [priority: medium]

  ⚠ Conflicts:
    - Over budget: 3 due task(s) need 45 min but only 30 min available (15 min short).

Planned 2 of 3 task(s) — 25 of 30 min used (5 min free).

Included:
  • Feeding — 10 min [high]
  • Litter change — 15 min [medium]

Skipped:
  • Play time — 20 min [low] (didn't fit remaining time)

================================================
Sorting & filtering demo — Biscuit
================================================

As added (deliberately out of order):
  19:00  Brushing          25 min [low   ] (todo)
  08:00  Morning walk      30 min [high  ] (todo)
  07:30  Medication        10 min [high  ] (todo)

Sorted by time — sort_by_time():
  07:30  Medication        10 min [high  ] (todo)
  08:00  Morning walk      30 min [high  ] (todo)
  19:00  Brushing          25 min [low   ] (todo)

Sorted by duration, shortest first — sort_by_duration():
  07:30  Medication        10 min [high  ] (todo)
  19:00  Brushing          25 min [low   ] (todo)
  08:00  Morning walk      30 min [high  ] (todo)

Pending only — filter_by_status(completed=False):
  08:00  Morning walk      30 min [high  ] (todo)
  07:30  Medication        10 min [high  ] (todo)

Completed only — filter_by_status(completed=True):
  19:00  Brushing          25 min [low   ] (done)

Tasks for 'Mochi' — tasks_for_pet('Mochi'):
  18:30  Play time         20 min [low   ] (todo)
  08:00  Feeding           10 min [high  ] (todo)
  13:00  Litter change     15 min [medium] (todo)

================================================
Recurring-task demo — complete_task() spawns next occurrence
================================================

Before: Mochi has 3 task(s).
Completed 'Feeding' (daily).
After:  Mochi has 4 task(s) (a new occurrence was spawned).
  new occurrence -> 08:00  Feeding           10 min [high  ] (todo) due 2026-07-08
  due today (2026-07-07)? False  — it waits for its due date.

```

## 🧪 Testing PawPal+

```bash
# Run the full test suite:
pytest

# Run with coverage:
pytest --cov
```

Sample test output:

```
# ==================================================================================================== test session starts =====================================================================================================
platform darwin -- Python 3.13.10, pytest-9.1.1, pluggy-1.6.0
rootdir: /Users/Admin/Desktop/SUMMER 2026/CODEPATH/AI110/ai110-module2show-pawpal-starter
plugins: anyio-4.14.0, cov-7.1.0
collected 24 items

tests/test_pawpal.py ........................                                                                                                                                                                          [100%]

===================================================================================================== 24 passed in 0.04s =====================================================================================================
(.venv) .../ai110-module2show-pawpal-starter>
```

## 📐 Smarter Scheduling

> Fill in once you've implemented scheduling logic.

| Feature | Method(s) | Notes |
|---------|-----------|-------|
| Task sorting | | e.g., by priority, duration |
| Filtering | | e.g., skip tasks if time runs out |
| Conflict handling | | e.g., overlapping time slots |
| Recurring tasks | | e.g., daily vs. weekly |

1. task sorting
    - Scheduler.sort_by_time() - orders tasks by their time
    - Scheduler.sort_by_duration() - orders tasks by their duration(duration_minutes);(ascending order; shortest - longest)
    - Scheduler.build_plan() - selects tasks by priority then shortest duration and returns the chosen plan sorted by the tasks' time
2. filtering
    - Owner.tasks_for_pet() - filter by pet
    - Scheduler.filter_by-status - filter by completion status
    - Task.needs_doing() - helps with filtering what's due today
3. conflict detection
    - Scheduler.detect_time_conflict() - detects clash in exact time for tasks for a given owner across all pets
    - Scheduler.detect_conflicts() - checks for exceeded time availability and duplicate task names for a given pet
4. recurring task logic
    - Scheduler.complete_task() - marks a task completed, spawns new occurrence for recurring ones based on their frequency
    - Task.mark_complete() - marks the task occurrence done
    - Task.due_date() - the day when a spawned occurrence is due
    - FREQUENCY_DAYS - for mapping the frequencies to numerical values eg daily, weekly etc
5. planning and explanation
    - Scheduler.build_plan() - makes the daily plan per pet within the time budget
    - Scheduler.all_owner_plans() - maps each plan to its respective pet
    - Scheduler.explain() - provides reasoning for the order of the tasks and a summary of what was planned or skipped and why


## 📸 Demo Walkthrough

### Main UI features & what you can do

Launch the app with `streamlit run app.py`. The page is a single scrolling form with these sections:

- **Owner** — type an owner name (starts blank). A **Start over** button clears everything and resets to a fresh, empty form without restarting the server.
- **Add a pet** — enter a pet name, its species, breed, and age, and set how many minutes are available for that pet today. Each pet carries its own time budget. A **medical condition** field is optional — leave it blank if there's none; when filled in it's shown beside the pet everywhere it appears, including above its daily plan. Profile details are descriptive only: they don't change how the schedule is built.
- **Add a task** — pick which pet the task belongs to, then set its title, duration, priority (low / medium / high), frequency (daily / weekly), and time of day.
- **Current pets & tasks** — lists every pet with its due tasks. Here you can:
  - **Sort** the list by Time, Priority, or Duration.
  - **Filter** by status (All / Pending / Completed).
  - **Done** — mark a task complete; a recurring task automatically spawns its next occurrence.
  - **Edit** — open an inline form to change any field of an existing task and save it.
  - Upcoming occurrences (not yet due) are hidden until their day arrives, so completing a recurring task doesn't clutter the list with a duplicate.
- **Build schedule** — generates today's plan per pet, shows time-conflict warnings, per-pet conflict warnings, the ordered plan as a table, and a "Why this plan?" explanation.

### Example workflow

1. Enter an **owner name** (e.g. *Jordan*).
2. **Add a pet**: `Biscuit`, dog, 60 minutes available.
3. **Add tasks** to Biscuit: *Medication* (10 min, high, 07:30), *Morning walk* (30 min, high, 08:00), *Brushing* (25 min, low, 19:00).
4. In **Current pets & tasks**, sort by Time to see them in the order you'd do them, or filter to Pending only.
5. Click **Build schedule** — PawPal+ fits the highest-priority tasks into the 60-minute budget, warns that the tasks are over budget, and explains which task it skipped and why.
6. Mark *Medication* **Done** — since it's a daily task, tomorrow's occurrence is scheduled automatically (and stays hidden until tomorrow).

### Key Scheduler behaviors shown

- **Sorting** — `sort_by_time()` and `sort_by_duration()` reorder a jumbled task list; `build_plan()` selects by priority first, shortest-duration as the tie-break.
- **Filtering** — `filter_by_status()` splits pending vs. completed; `Owner.tasks_for_pet()` filters by pet; `Task.needs_doing()` decides what's actually due today.
- **Time-budget planning** — greedy "skip and keep going": a task that doesn't fit is skipped so leftover minutes aren't wasted, and `explain()` reports what was planned vs. skipped.
- **Conflict warnings** — `detect_time_conflicts()` catches two tasks booked at the same clock time across all pets; `detect_conflicts()` flags over-budget days and duplicate task names per pet.
- **Recurring tasks** — `complete_task()` marks a task done and spawns the next occurrence with a future `due_date` based on its frequency.

### Sample CLI output (`python main.py`)

`main.py` runs the same logic headlessly against a two-pet sample scenario, so you can see every behavior in one run:

```
================================================
Today's Schedule for Jordan
================================================

⚠ Time conflicts (the owner can't be in two places at once):
  - Time conflict at 08:00: Biscuit's Morning walk, Mochi's Feeding overlap.

Biscuit (dog) - 60 min available
------------------------------------------------
  [ ] 07:30  Medication        10 min [priority: high]
  [ ] 08:00  Morning walk      30 min [priority: high]

  ⚠ Conflicts:
    - Over budget: 3 due task(s) need 65 min but only 60 min available (5 min short).

Planned 2 of 3 task(s) — 40 of 60 min used (20 min free).

Included:
  • Medication — 10 min [high]
  • Morning walk — 30 min [high]

Skipped:
  • Brushing — 25 min [low] (didn't fit remaining time)

Mochi (cat) - 30 min available
------------------------------------------------
  [ ] 08:00  Feeding           10 min [priority: high]
  [ ] 13:00  Litter change     15 min [priority: medium]

  ⚠ Conflicts:
    - Over budget: 3 due task(s) need 45 min but only 30 min available (15 min short).

Planned 2 of 3 task(s) — 25 of 30 min used (5 min free).

Included:
  • Feeding — 10 min [high]
  • Litter change — 15 min [medium]

Skipped:
  • Play time — 20 min [low] (didn't fit remaining time)

================================================
Sorting & filtering demo — Biscuit
================================================

As added (deliberately out of order):
  19:00  Brushing          25 min [low   ] (todo)
  08:00  Morning walk      30 min [high  ] (todo)
  07:30  Medication        10 min [high  ] (todo)

Sorted by time — sort_by_time():
  07:30  Medication        10 min [high  ] (todo)
  08:00  Morning walk      30 min [high  ] (todo)
  19:00  Brushing          25 min [low   ] (todo)

Sorted by duration, shortest first — sort_by_duration():
  07:30  Medication        10 min [high  ] (todo)
  19:00  Brushing          25 min [low   ] (todo)
  08:00  Morning walk      30 min [high  ] (todo)

Pending only — filter_by_status(completed=False):
  08:00  Morning walk      30 min [high  ] (todo)
  07:30  Medication        10 min [high  ] (todo)

Completed only — filter_by_status(completed=True):
  19:00  Brushing          25 min [low   ] (done)

Tasks for 'Mochi' — tasks_for_pet('Mochi'):
  18:30  Play time         20 min [low   ] (todo)
  08:00  Feeding           10 min [high  ] (todo)
  13:00  Litter change     15 min [medium] (todo)

================================================
Recurring-task demo — complete_task() spawns next occurrence
================================================

Before: Mochi has 3 task(s).
Completed 'Feeding' (daily).
After:  Mochi has 4 task(s) (a new occurrence was spawned).
  new occurrence -> 08:00  Feeding           10 min [high  ] (todo) due 2026-07-08
  due today (2026-07-07)? False  — it waits for its due date.
```

**Screenshot or video** *(optional)*: <!-- Insert a screenshot or link to a demo video here -->
