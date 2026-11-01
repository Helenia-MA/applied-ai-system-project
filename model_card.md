# PawPal+ Project Reflection

## Limitations and biases
- suggestions are solely based on the information in the knowledge folder, thus may not fully cater for rare breeds, species or conditions
- since we're using greedy scheduling, the planner prioritizes high-priority and shorter tasks, which can then leady to longer important tasks being at a disadvantage
- since the plan focuses on each pet separately, optimization for an individual pet may be suboptimal for the owner overally across all pets

## AI misuse prevention
the suggestions could be treated as veterinary diagnosis; we resolve this by clearly indicating and labelling the outputs as planning support and not medical advice, and adding a message recommending vet confirmation for health decisions

## AI reliability
I realized the retrieval quality mattered a lot more than the model in the suggested task list generation. Constraining the suggestions to the retrieved chunks helped narrowing down and making the end product more dependable

## AI collaboration
It helped me a lot in planning out and implementing the RAG feature. I loved how it formatted the care_kb.md for easier and more efficient retrieval of the needed information chunks for the different pet species and conditions.

## 1. System Design

**a. Initial design**

- Briefly describe your initial UML design.
- What classes did you include, and what responsibilities did you assign to each?

my design entails 3 classes: task, owner and scheduler;
    * task:
        - id, name, duration, priority
    * pet:
        - name, species, total time availability, tasks, next_id
        - add task, edit task, set availability
    * owner:
        - name, pets
        - add_pets
    * scheduler:
        - build plan(sort and filters tasks to fit), all_owner_plans(to return all plans each assigned to the respective pet for the owner), explanation

**b. Design changes**

- Did your design change during implementation?
- If yes, describe at least one change and why you made it.
* Added frequency and completed attributes to the Task class so we can handle repeating tasks and can also allow user to keep track of the completed/uncompleted tasks and have a chance to add some of the dropped off tasks back to the list if some of the completed ones took shorter time than allocated.
* added an all_tasks function to allow the owner to see all their added tasks


---

## 2. Scheduling Logic and Tradeoffs

**a. Constraints and priorities**

- What constraints does your scheduler consider (for example: time, priority, preferences)?
- How did you decide which constraints mattered most?


**b. Tradeoffs**

- Describe one tradeoff your scheduler makes.
- Why is that tradeoff reasonable for this scenario?
The scheduler produces the ordered to-do list that fits the daily time budget and not necessarily a true calendar. It only uses the task's provided time to order the list rather than as a basis for fitting tasks to the schedule. Thus our conflict constraint only catches exact time matches and not tasks with overlapping times.

This is a reasonable tradeoff in this scenario since the main focus of the scheduler is in helping the owner prioritize and decide what to do first and not necessarily when. As long as the tasks are catered to fit in the available given time scope, the exact time a specific task is done is more flexible and not as rigid.
---

## 3. AI Collaboration

**a. How you used AI**

- How did you use AI tools during this project (for example: design brainstorming, debugging, refactoring)?
- What kinds of prompts or questions were most helpful?
I used it in designing the uml, brainstorming the optimal designs and logic for the features I wanted to implement, debugging and testing the codes and ensuring changes made in one file were updated accordingly in all the files dependent on it.

when i gave it specific prompts with a step by step guide say on sorting on what it should start with and my preferred outputs or when i included a small example it helped with getting a more accurate response.

**b. Judgment and verification**

- Describe one moment where you did not accept an AI suggestion as-is.
- How did you evaluate or verify what the AI suggested?
In the beginning, it offered to have tasks as an attribute of owner without its own class and have us return one list of tasks for the owner for all its pets.
I decided to add the class and have a function mapping each list to its respective pet for an owner with multiple pets since it felt more intuitive and worked well in distinguishing each pet's tasks especially in cases where there are similar tasks for each one.

---

## 4. Testing and Verification

**a. What you tested**

- What behaviors did you test?
- Why were these tests important?
I tested for sorting, the recurrence logic and conflict detection
sorting correctness was important in ensuring that the priorities of the tasks were considered and we attempted fitting as many tasks as possible within the time budget by prioritizing the shortest ones first. I also tested that when there is free time left that could fit medium priority tasks while a remaining high task was too long, the scheduler wouldn't stop but continue adding the medium priority tasks to the list
the recurrence logic tests were important in ensuring the new occurrences were not marked as complete, they appeared on the day they were due and stopped after the frequency was over
conflic detection tests were for the warning message when two tasks across all the owner's pets had the same time.

**b. Confidence**

- How confident are you that your scheduler works correctly?
90%
- What edge cases would you test next if you had more time?
the tasks with overlapping times
tasks with long durations but critical

---

## 5. Reflection

**a. What went well**

- What part of this project are you most satisfied with?
   * I was satisfied with how well the frequency logic came together

**b. What you would improve**

- If you had another iteration, what would you improve or redesign?
   * I would improve the priority, right the aim is to just fit as many tasks as possible, with time I could brainstorm a logic that put more things into consideration

**c. Key takeaway**

- What is one important thing you learned about designing systems or working with AI on this project?
   * That the best way to get good results is to work on small chunks of the app and give it the context it needs.
