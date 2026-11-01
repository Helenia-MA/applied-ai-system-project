# PawPal+ Final Project

PawPal+ is a pet-care planning assistant built with Streamlit. It helps a pet owner organize care tasks, generate a daily schedule, and use retrieval-augmented AI to suggest new tasks based on a small care knowledge base.

## Original Project

The original project was PawPal+ from Module 2. It initially focused on modeling owners, pets, and care tasks, then using a greedy scheduler to fit tasks into each pet's daily time budget while explaining what fit and what had to be skipped.

The original version already supported task sorting, filtering, recurring tasks, and conflict detection.

For this final version, I kept the core scheduler and added grounded AI suggestions, logging, and stronger documentation.

## What It Does

PawPal+ helps a pet owner:

- add pets and care tasks
- schedule tasks by priority and available time
- detect conflicts and recurring-task behavior
- retrieve relevant care guidance before generating AI suggestions
- accept AI suggestions into the real schedule

Once the owner accepts the suggested tasks, they are added to the task list and ranked alongside all the other tasks.

## Architecture Overview

The system is split into a few main pieces:

- [`app.py`](app.py) is the Streamlit UI.
- [`pawpal_system.py`](pawpal_system.py) contains the owner, pet, task, and scheduler logic.
- [`retrieval.py`](retrieval.py) selects the relevant care guidance from [`knowledge/care_kb.md`](knowledge/care_kb.md).
- [`advisor.py`](advisor.py) turns that retrieved guidance into structured AI suggestions and validates them.
- [`logging_setup.py`](logging_setup.py) records audit information and guardrail events.
- [`tests/`](tests) checks scheduling behavior, retrieval, guardrails, logging, and the accept-to-plan integration path.

The diagram source is in [`diagrams/architecture.mmd`](diagrams/architecture.mmd). It shows the flow from human input to retrieval, suggestion generation, acceptance, scheduling, and testing.

## Setup Instructions

1. Create and activate a virtual environment.

   ```bash
   python -m venv .venv
   source .venv/bin/activate
   ```

2. Install the project dependencies.

   ```bash
   pip install -r requirements.txt
   ```

3. If you want the AI suggestion flow, set a Gemini API key in `.env`.

   ```bash
   cp .env.example .env
   ```

   Add either `GEMINI_API_KEY` or `GOOGLE_API_KEY`. If you do not want to use the model, set `USE_LLM=0` and the rest of the app still works.

4. Run the Streamlit app.

   ```bash
   streamlit run app.py
   ```

5. Run the CLI demo if you want a headless walkthrough.

   ```bash
   python main.py
   ```

6. Run the tests.

   ```bash
   pytest
   ```

## Sample Interactions

### 1) Retrieval-backed suggestion

**Input:**
```text
- Pet: Kovu
- Species: Dog
- Breed: Labrador Retriever
- Medical condition: hip dysplasia
```

**Output/Result:**

The advisor retrieves guidance such as `dog-hip-dysplasia` and can suggest low-impact activities like a swim session.

```text
Retrieved 2 guidance chunk(s):
  - dog-hip-dysplasia
  - dog-general-dental

5 suggestion(s), each citing its source:
  12:00  Swimming session   15 min [high] <- dog-hip-dysplasia
```

### 2) Guardrail warning for restricted activity

**Input:**
```text
- Pet: Kovu
- Profile guidance says to avoid stairs
- Existing task: Stairs practice
```

**Output/Result:**

The scheduler flags the task instead of silently accepting it.

```text
Activities to avoid for this pet: agility, jumping, running, stairs

⚠ 'Stairs practice' involves stairs, which Kovu's care profile says to avoid.
```

### 3) Accepting a suggestion changes the schedule

**Input:**
```text
- Current tasks: Brushing (25 min, low priority)
- Suggested task: Medication (10 min, high priority)
- Available time: 30 min
```

**Output/Result:**

After the suggestion is accepted, the schedule changes and the UI reports the budget impact.

```text
Added 'Medication' (+10 min) to Kovu. Kovu has 20 min remaining. Regenerate the schedule to see the new plan.

Plan after accepting:
  07:30  Medication        10 min [high]
```

## Design Decisions

PawPal+ uses a greedy scheduler rather than an optimizer. That keeps the behavior easy to explain and makes the plan deterministic, but it means the schedule is not always globally optimal.

The AI layer is retrieval-augmented, thus the system is narrower than a general chatbot, but the answers are grounded in the selected pet-care knowledge base and easier to audit.

Suggested tasks are not written directly into the schedule. They become ordinary tasks only after the owner accepts them. That keeps the human in control and makes the UI safer to use.

Logging and guardrails are built in so the app can explain what it did, what it retrieved, and why a suggestion was rejected.

## Testing Summary

#### What worked:

- task sorting by time and duration
- greedy plan building and time-budget handling
- recurring-task spawning
- conflict detection
- retrieval and suggestion validation
- logging configuration and file output
- the end-to-end accept -> plan integration test

#### What did not work automatically:

- live AI suggestions need a valid Gemini API key
- the app falls back to a safe degraded mode when the key or knowledge base is unavailable

#### What I learned:

- keeping the retrieval, validation, and scheduling separate made the system easier to test
- I tried to ensure that the owner stayed in control of accepting suggestions so that the final list wasn't overtaken solely by the suggested tasks
- Having clear logs and explicit guardrails makes AI behavior much easier to understand and trust

### pytest
```
================================== test session starts ==================================
platform darwin -- Python 3.13.10, pytest-9.0.3, pluggy-1.6.0
rootdir: /Users/Admin/applied-ai-system-project
plugins: anyio-4.13.0
collected 125 items

tests/test_advisor.py ................................................            [ 38%]
tests/test_logging_setup.py ................                                      [ 51%]
tests/test_pawpal.py .......................................                      [ 82%]
tests/test_retrieval.py ......................                                    [100%]

================================== 125 passed in 1.32s ==================================
```
## Notes
- Reflection: [`model_card.md`](model_card.md)
- Architecture source: [`diagrams/architecture.mmd`](diagrams/architecture.mmd)
- UML source: [`diagrams/uml.mmd`](diagrams/uml.mmd)
- Main app: [`app.py`](app.py)
- CLI demo: [`main.py`](main.py)
