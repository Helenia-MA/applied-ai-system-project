from datetime import date, time

import streamlit as st
from advisor import llm_enabled, suggest_care_tasks, unavailable_reason
from logging_setup import setup_logging
from pawpal_system import (
    SOURCE_OWNER,
    Task,
    Pet,
    Owner,
    Scheduler,
    PRIORITY_VALUES,
    PRIORITY_LABELS,
)
from retrieval import KnowledgeBaseError, avoid_keywords, retrieve

# Streamlit re-runs this whole file on every interaction; setup_logging() is
# idempotent, so this configures handlers once rather than stacking a new pair
# on each click.
LOG_PATH = setup_logging()

st.set_page_config(page_title="PawPal+", page_icon="🐾", layout="centered")

st.title("🐾 PawPal+")

st.markdown(
    """
Welcome to PawPal+ — a pet-care planning assistant.

Add your pets and their care tasks, then generate a daily plan that respects each pet's
time budget and priorities, explains its reasoning, and warns about scheduling conflicts.
"""
)

with st.expander("Scenario", expanded=True):
    st.markdown(
        """
**PawPal+** is a pet care planning assistant. It helps a pet owner plan care tasks
for their pet(s) based on constraints like time, priority, and preferences.
"""
    )

with st.expander("What you need to build", expanded=True):
    st.markdown(
        """
system MVP:
- Represents pet care tasks (what needs to happen, how long it takes, priority)
- Represents the pet and the owner (basic info and preferences)
- Builds a plan/schedule for a day that chooses and orders tasks based on constraints
- Explains the plan (why each task was chosen and when it happens)
"""
    )

st.divider()

st.subheader("Owner")
owner_name = st.text_input("Owner name", value="", placeholder="e.g. Jordan")

# Create the Owner once and keep it in the session vault; reuse it every rerun.
if "owner" not in st.session_state:
    st.session_state.owner = Owner(owner_name)
owner = st.session_state.owner
# Keep the owner's name in sync with the input on every rerun (so editing it,
# not just the first value, actually takes effect).
owner.name = owner_name

# Start fresh: wipe pets/tasks and any stashed state, then rerun blank.
if st.button("Start over"):
    st.session_state.clear()
    st.rerun()

# One scheduler and one notion of "today" for the whole render.
scheduler = Scheduler()
today = date.today()


def restricted_activities(pet):
    """Activities this pet's care guidance says to avoid, or [] if unavailable.

    Wrapped so a missing or broken knowledge base costs the warnings only — the
    schedule itself is built without any of this and must keep working.
    """
    try:
        return avoid_keywords(retrieve(pet))
    except KnowledgeBaseError:
        return []


def due_minutes(pet) -> int:
    """Total minutes for tasks that are due today and not completed yet."""
    return sum(task.duration_minutes for task in pet.tasks if task.needs_doing(today))

# Show and clear any one-off message stashed before a st.rerun() (see "Done").
if "flash" in st.session_state:
    st.success(st.session_state.pop("flash"))

st.divider()

# --- Add a pet -----------------------------------------------------------
# Grouped in a form so the fields commit together on submit (no per-widget
# "Press Enter to apply" state), and clear themselves after a pet is added.
st.subheader("Add a pet")
with st.form("add_pet", clear_on_submit=True, enter_to_submit=False):
    col1, col2, col3 = st.columns(3)
    with col1:
        new_pet_name = st.text_input("Pet name", value="", placeholder="e.g. Mochi")
    with col2:
        new_species = st.text_input("Species", value="", placeholder="e.g. dog, rabbit, parrot")
    with col3:
        pet_minutes = st.number_input("Time available (min)", min_value=0, max_value=600, value=60)

    col4, col5 = st.columns(2)
    with col4:
        new_breed = st.text_input("Breed", value="", placeholder="e.g. tabby, labrador")
    with col5:
        # 0 doubles as "not given" — a pet under a year old reads as 0 anyway,
        # and we store None so describe() can leave the age out entirely.
        new_age = st.number_input(
            "Age (years, 0 if unknown)", min_value=0, max_value=40, value=0
        )

    new_condition = st.text_input(
        "Medical condition (optional)",
        value="",
        placeholder="e.g. arthritis, diabetes — leave blank if none",
    )
    add_pet = st.form_submit_button("Add pet")

if add_pet:
    if not new_pet_name.strip():
        st.warning("Give your pet a name first.")
    else:
        owner.add_pet(
            new_pet_name.strip(),
            new_species.strip(),
            int(pet_minutes),
            breed=new_breed.strip(),
            # Blank inputs become None rather than 0/"" so "unknown" and "none
            # known" stay distinguishable from a real value.
            age=int(new_age) or None,
            medical_condition=new_condition.strip() or None,
        )
        st.success(f"Added {new_pet_name.strip()} to {owner.name or 'you'}.")

st.divider()

# --- Add a task to a pet -------------------------------------------------
st.subheader("Add a task")
if not owner.pets:
    st.info("Add a pet first, then you can give it tasks.")
else:
    pet_names = [pet.name for pet in owner.pets]
    # Same idea as "Add a pet": one form, one submit, fields clear afterward.
    with st.form("add_task", clear_on_submit=True):
        chosen_pet = st.selectbox("Which pet?", pet_names)

        col1, col2, col3 = st.columns(3)
        with col1:
            task_title = st.text_input("Task title", value="", placeholder="e.g. Morning walk")
        with col2:
            duration = st.number_input("Duration (minutes)", min_value=1, max_value=240, value=20)
        with col3:
            priority = st.selectbox("Priority", ["low", "medium", "high"], index=2)

        col4, col5 = st.columns(2)
        with col4:
            frequency = st.selectbox("Frequency", ["daily", "weekly"])
        with col5:
            task_time = st.time_input("Time", value=time(9, 0))
        add_task = st.form_submit_button("Add task")

    if add_task:
        if not task_title.strip():
            st.warning("Give the task a title first.")
        else:
            # Find the chosen pet, then add the task using our real method.
            pet = owner.pets[pet_names.index(chosen_pet)]
            pet.add_task(
                task_title.strip(),
                int(duration),
                PRIORITY_VALUES[priority],
                frequency=frequency,
                time=task_time.strftime("%H:%M"),
            )
            st.success(f"Added '{task_title.strip()}' to {pet.name}.")

st.divider()

# --- Suggest care tasks (retrieval-augmented) ----------------------------
# A fourth way to create tasks, alongside the manual form above. The pet's
# profile fields are looked up against knowledge/care_kb.md, and only the
# guidance that matches is sent to the model — so suggestions are grounded in
# this pet's actual species, breed, age, and condition rather than invented.
st.subheader("Suggest care tasks")
st.caption(
    "Looks up care guidance matching this pet's species, breed, age, and medical "
    "condition, then proposes tasks based only on what it found. Nothing is added "
    "to the schedule until you accept it."
)

if not owner.pets:
    st.info("Add a pet first — suggestions are built from its profile.")
elif not llm_enabled():
    # Degraded mode. Everything else on the page keeps working, so say so
    # plainly rather than hiding the section or showing an error.
    st.info(f"{unavailable_reason()}  \nThe rest of PawPal+ works as normal.")
else:
    suggest_names = [pet.name for pet in owner.pets]
    scol1, scol2 = st.columns([3, 1])
    with scol1:
        suggest_for = st.selectbox("Which pet?", suggest_names, key="suggest_pet")
    with scol2:
        # Blank label pushes the button down so it lines up with the selectbox.
        st.write("")
        run_suggest = st.button("Suggest tasks", key="suggest_go")

    if run_suggest:
        pet = owner.pets[suggest_names.index(suggest_for)]
        # The call takes a few seconds, so show progress rather than freezing.
        with st.spinner(f"Looking up care guidance for {pet.name}…"):
            result = suggest_care_tasks(pet)
        # Held in session state so accepting one suggestion doesn't discard the
        # rest on the rerun, and doesn't cost another API call.
        st.session_state.setdefault("suggestions", {})[pet.name] = result
        st.rerun()

    pending = st.session_state.get("suggestions", {})
    for pet_name, result in list(pending.items()):
        pet = next((p for p in owner.pets if p.name == pet_name), None)
        if pet is None:
            # The pet was removed (e.g. "Start over"); drop its stale suggestions.
            pending.pop(pet_name, None)
            continue

        st.markdown(f"**Suggestions for {pet_name}**")
        if result.chunk_ids:
            # Shown so the owner can see which guidance the model was given —
            # every suggestion below has to cite one of these.
            st.caption("Grounded in: " + ", ".join(f"`{c}`" for c in result.chunk_ids))

        if not result.available:
            st.warning(result.reason)
        elif not result.suggestions:
            st.info(result.reason or "Nothing to suggest for this pet right now.")
        else:
            for index, suggestion in enumerate(list(result.suggestions)):
                c1, c2, c3, c4, c5 = st.columns([1.5, 3.5, 2, 2, 1.5])
                c1.write(suggestion.time)
                c2.write(f"{suggestion.name} ({suggestion.frequency})")
                c3.write(f"{suggestion.duration_minutes} min")
                c4.write(PRIORITY_LABELS[suggestion.priority])
                if c5.button("Accept", key=f"accept_{pet_name}_{index}_{suggestion.name}"):
                    # The one place a suggestion becomes a real task. From here it
                    # competes for the time budget like anything else the owner added.
                    pet.accept_suggestion(suggestion)
                    total_due = due_minutes(pet)
                    over_by = max(0, total_due - pet.available_minutes)
                    remaining = max(0, pet.available_minutes - total_due)
                    result.suggestions.pop(index)
                    if not result.suggestions:
                        pending.pop(pet_name, None)
                    flash = (
                        f"Added '{suggestion.name}' (+{suggestion.duration_minutes} min) to {pet_name}. "
                    )
                    if over_by:
                        flash += f"{pet_name} is now {over_by} min over budget. "
                    else:
                        flash += f"{pet_name} has {remaining} min remaining. "
                    flash += "Regenerate the schedule to see the new plan."
                    st.session_state["flash"] = flash
                    st.rerun()
                st.caption(
                    f"↳ {suggestion.rationale} · source: `{suggestion.source_chunk_id}`"
                )

        if result.rejected:
            # Surfaced rather than hidden: the guardrails rejecting a suggestion
            # is the system working, and it's worth being able to see why.
            with st.expander(f"{len(result.rejected)} filtered out by guardrails"):
                for reason in result.rejected:
                    st.text(reason)

        if st.button("Dismiss these", key=f"dismiss_{pet_name}"):
            pending.pop(pet_name, None)
            st.rerun()

    st.caption(
        "⚠️ Suggestions come from a small illustrative care knowledge base and are "
        "not veterinary advice. Check anything medical with your vet."
    )
    if LOG_PATH:
        # Every lookup, token count, and guardrail rejection is recorded here.
        st.caption(f"Activity is logged to `{LOG_PATH}`.")

st.divider()

# --- Current pets & tasks ------------------------------------------------
st.subheader("Current pets & tasks")
if not owner.pets:
    st.info("No pets yet. Add one above.")
else:
    # Sort/filter controls drive the Scheduler helpers below, so the owner can
    # reorder and narrow the list without touching the underlying tasks.
    fcol, scol = st.columns(2)
    with fcol:
        status_filter = st.selectbox(
            "Show", ["All", "Pending", "Completed"], key="task_status_filter"
        )
    with scol:
        sort_choice = st.selectbox(
            "Sort by", ["Time", "Priority", "Duration"], key="task_sort_choice"
        )

    for pet in owner.pets:
        profile = pet.describe()
        st.markdown(
            f"**{pet.name}**"
            + (f" ({profile})" if profile else "")
            + f" — {pet.available_minutes} min available"
        )
        if pet.medical_condition:
            st.caption(f"🩺 {pet.medical_condition}")

        # Hide occurrences that aren't due yet (the future recurrences spawned
        # when a recurring task is completed); they reappear on their due date.
        tasks = [t for t in pet.tasks if not (t.due_date and t.due_date > today)]

        # Apply the chosen filter, then the chosen sort, via Scheduler methods.
        if status_filter == "Pending":
            tasks = scheduler.filter_by_status(tasks, completed=False)
        elif status_filter == "Completed":
            tasks = scheduler.filter_by_status(tasks, completed=True)

        if sort_choice == "Time":
            tasks = scheduler.sort_by_time(tasks)
        elif sort_choice == "Duration":
            tasks = scheduler.sort_by_duration(tasks, ascending=True)
        else:  # Priority — high first, shortest task as tie-break.
            tasks = sorted(tasks, key=lambda t: (-t.priority, t.duration_minutes))

        if tasks:
            # Iterate a snapshot: completing a task appends a new one to pet.tasks,
            # and we don't want to mutate the list we're looping over.
            for t in list(tasks):
                c1, c2, c3, c4, c5, c6 = st.columns([2, 3, 2, 2, 1.5, 1.5])
                c1.write(t.time)
                c2.write(f"{t.name} ({t.frequency})")
                c3.write(f"{t.duration_minutes} min")
                c4.write(PRIORITY_LABELS[t.priority])
                if t.completed:
                    c5.write("✓ done")
                elif c5.button("Done", key=f"done_{pet.name}_{t.id}"):
                    # Mark complete; for a recurring task this spawns the next one.
                    new = scheduler.complete_task(pet, t.id, today)
                    if new is not None:
                        st.session_state["flash"] = (
                            f"Completed '{t.name}'. Next {new.frequency} occurrence "
                            f"scheduled for {new.due_date}."
                        )
                    else:
                        st.session_state["flash"] = f"Completed '{t.name}'."
                    st.rerun()
                # Toggle an inline edit form for this task (remembered per rerun).
                if c6.button("Edit", key=f"edit_{pet.name}_{t.id}"):
                    st.session_state["editing"] = (pet.name, t.id)
                    st.rerun()

                # Render the edit form directly under the row being edited.
                if st.session_state.get("editing") == (pet.name, t.id):
                    with st.form(key=f"editform_{pet.name}_{t.id}"):
                        st.caption(f"Editing '{t.name}'")
                        e1, e2 = st.columns(2)
                        with e1:
                            new_name = st.text_input("Task title", value=t.name)
                            new_duration = st.number_input(
                                "Duration (minutes)", min_value=1, max_value=240,
                                value=t.duration_minutes,
                            )
                            new_priority = st.selectbox(
                                "Priority", ["low", "medium", "high"],
                                index=["low", "medium", "high"].index(
                                    PRIORITY_LABELS[t.priority]
                                ),
                            )
                        with e2:
                            new_frequency = st.selectbox(
                                "Frequency", ["daily", "weekly"],
                                index=["daily", "weekly"].index(t.frequency)
                                if t.frequency in ("daily", "weekly") else 0,
                            )
                            # Parse the stored "HH:MM" back into a time for the picker.
                            hh, mm = (int(x) for x in t.time.split(":"))
                            new_time = st.time_input("Time", value=time(hh, mm))
                            new_completed = st.checkbox("Completed", value=t.completed)

                        save, cancel = st.columns(2)
                        if save.form_submit_button("Save"):
                            if not new_name.strip():
                                st.warning("Task title can't be empty.")
                            else:
                                pet.edit_task(
                                    t.id,
                                    name=new_name.strip(),
                                    duration_minutes=int(new_duration),
                                    priority=PRIORITY_VALUES[new_priority],
                                    frequency=new_frequency,
                                    completed=new_completed,
                                    time=new_time.strftime("%H:%M"),
                                )
                                st.session_state.pop("editing", None)
                                st.session_state["flash"] = f"Updated '{new_name.strip()}'."
                                st.rerun()
                        if cancel.form_submit_button("Cancel"):
                            st.session_state.pop("editing", None)
                            st.rerun()
        elif pet.tasks:
            # Some tasks exist but none are showing (filtered out, or only
            # future occurrences remain that aren't due yet).
            if status_filter == "All":
                st.caption("Nothing due right now — upcoming occurrences are hidden until their day.")
            else:
                st.caption(f"No {status_filter.lower()} tasks.")
        else:
            st.caption("No tasks yet.")

st.divider()

st.subheader("Build schedule")
st.caption("Plans each pet against its time budget, honoring priority, and flags conflicts.")

if st.button("Generate schedule"):
    if not owner.pets:
        st.info("Add a pet and some tasks first.")
    else:
        # Owner-wide time conflicts: two tasks (same or different pets) at once.
        # These are the most actionable warning for an owner (one person can't be
        # in two places), so surface them up top, before any per-pet plan.
        time_conflicts = scheduler.detect_time_conflicts(owner, today)
        if time_conflicts:
            st.warning(
                "⏰ **Scheduling conflicts** — you're booked for two things at once. "
                "Move one of each pair to a different time:\n\n"
                + "\n".join(f"- {w}" for w in time_conflicts)
            )
        else:
            st.success("✅ No time conflicts — every task is at its own time slot.")

        plans = scheduler.all_owner_plans(owner, today)
        for pet, plan in plans.items():
            profile = pet.describe()
            st.markdown(
                f"### {pet.name}"
                + (f" ({profile})" if profile else "")
                + f" — {pet.available_minutes} min"
            )
            # Surfaced with the plan so the owner has the condition in mind while
            # working through the day's care (it doesn't change the ordering).
            if pet.medical_condition:
                st.info(f"🩺 Medical condition: {pet.medical_condition}")

            # Per-pet conflicts (over budget, duplicate task names).
            conflicts = scheduler.detect_conflicts(pet, today)
            for warning in conflicts:
                st.warning(warning)

            # Retrieved care guidance also judges the tasks already on the list:
            # anything involving an activity this pet should avoid gets flagged.
            # Warning only — the owner decides whether to move or drop it, so a
            # flagged task can still appear in the plan below.
            for warning in scheduler.detect_restricted_tasks(
                pet, restricted_activities(pet), today
            ):
                st.warning(f"🚫 {warning}")

            if plan:
                # A clean table reads far better than a bulleted list for the
                # order the owner will actually work through the day.
                st.table(
                    [
                        {
                            "Time": t.time,
                            "Task": t.name,
                            "Minutes": t.duration_minutes,
                            "Priority": PRIORITY_LABELS[t.priority],
                            # Provenance travels into the plan, so the owner can
                            # tell at a glance which entries they wrote and which
                            # came from accepted care guidance.
                            "From": "you" if t.source == SOURCE_OWNER
                                    else f"suggested ({t.source_note})",
                        }
                        for t in plan
                    ]
                )
            else:
                st.caption("Nothing scheduled today.")

            # Reasoning: summarize planned vs. the due tasks that didn't fit.
            skipped = [t for t in pet.tasks if t.needs_doing(today) and t not in plan]
            with st.expander("Why this plan?"):
                st.text(scheduler.explain(plan, skipped, pet.available_minutes))
