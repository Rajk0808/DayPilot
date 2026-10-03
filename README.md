# DayPilot Domain Model — Complete Overview

## 1. Purpose of the Domain Layer

The DayPilot domain layer contains the core planning rules and state transitions of the system.

It is responsible for:

- Representing goals and task hierarchies.
- Representing independent task dependencies.
- Representing calendar availability and constraints.
- Representing schedule blocks and plans.
- Determining task execution and scheduling eligibility.
- Recording observations and deriving task progress.
- Recovering remaining work.
- Computing a new plan when something changes.
- Validating that a proposed plan is internally consistent.
- Applying a validated replanning result atomically.

The domain layer does **not** depend on FastAPI, HTTP handlers, database persistence, notification delivery, Telegram, iPhone widgets, or other infrastructure.

---

# 2. Domain Model at a Glance

```text
                            ┌───────────────┐
                            │     Goal      │
                            └───────┬───────┘
                                    │ owns root tasks
                                    ▼
                            ┌───────────────┐
                            │     Task      │
                            └───────┬───────┘
                                    │
                    ┌───────────────┼────────────────┐
                    │               │                │
                    ▼               ▼                ▼
             parent / children   status       scheduling_status
                    │
                    │ hierarchy
                    │
                    ▼
             ┌─────────────────┐
             │ DependencyGraph │
             └────────┬────────┘
                      │
               prerequisites /
                 dependents
                      │
                      ▼
             execution eligibility


 CalendarEvents ─────────────┐
                             │
 Hard Constraints ───────────┼──► available TimeWindows
                             │
                             ▼
                       ┌──────────┐
                       │ Scheduler│
                       └────┬─────┘
                            │
                            ▼
                      ScheduleBlock
                            │
                            ▼
                          Plan


 Observation
     │
     ▼
 Observation history
     │
     ├──► TaskStatus
     └──► RemainingWork
                     │
                     ▼
                  Replanner
                     │
                     ▼
              ReplanningResult
                     │
                     ▼
          Atomic PlannerState commit
```

---

# 3. Core Domain Entities

## 3.1 Goal

A `Goal` groups a set of root tasks.

### Responsibility

A Goal:

- Has a stable identity.
- Owns root tasks.
- Cannot contain duplicate root tasks.
- A root task cannot simultaneously belong to another Goal.
- A root task must not have a parent task.

### Relationship

```text
Goal
 ├── root task A
 ├── root task B
 └── root task C
```

Tasks below those roots form the task hierarchy.

---

# 3.2 Task

`Task` is the central unit of work.

A task can be:

- Atomic — no children.
- Composite — contains children.

### Important fields

```text
id
title
description
status
priority
parent
children
estimated_duration
deadline
metadata
scheduling_status
```

### Task hierarchy

```text
Goal
 └── A
      ├── B
      │    ├── D
      │    └── E
      └── C
```

The hierarchy answers:

> "What work belongs inside what other work?"

It does **not** answer:

> "What must be completed before what?"

That second question belongs to `DependencyGraph`.

### Hierarchy rules

A child:

- Cannot already belong to another parent.
- Cannot be added twice to the same parent.
- Cannot create a self-cycle.
- Cannot create a descendant cycle.
- Cannot produce inconsistent parent/children links.

---

# 3.3 DependencyGraph

`DependencyGraph` is intentionally separate from the task hierarchy.

It stores:

```text
tasks:
    task_id → Task

prerequisites:
    dependent_id → prerequisite_ids

dependents:
    prerequisite_id → dependent_ids
```

Example:

```text
A ───► C
B ───► C
```

means:

```text
C requires A
C requires B
```

### Dependency rules

- Both tasks must be registered.
- Task identity matters, not only task ID.
- A task cannot depend on itself.
- Duplicate dependencies are rejected.
- Dependencies connecting tasks from the same task tree are rejected.
- Dependencies creating a cycle are rejected.
- A task cannot be unregistered while it still has prerequisites or dependents.

### Graph operations

```text
register_task()
unregister_task()

add_dependency()
remove_dependency()

get_prerequisites()
get_dependents()
has_dependency()

can_execute()
get_ready_tasks()
get_execution_order()
```

---

# 4. Task Status Model

`TaskStatus` represents execution state.

The domain uses:

```text
NOT_STARTED
IN_PROGRESS
COMPLETED
BLOCKED
CANCELLED
```

## Atomic task status

An atomic task stores its status directly.

## Composite task status

A composite task derives its status recursively from child statuses.

The precedence implemented is:

```text
1. All children NOT_STARTED
       → NOT_STARTED

2. Any child BLOCKED
       → BLOCKED

3. Any child IN_PROGRESS
       → IN_PROGRESS

4. Any child CANCELLED
       → IN_PROGRESS

5. All children COMPLETED
       → COMPLETED

6. Otherwise
       → IN_PROGRESS
```

### Example

```text
Parent
 ├── A = COMPLETED
 ├── B = COMPLETED
 └── C = IN_PROGRESS

Parent = IN_PROGRESS
```

### Empty composite

A composite task with no children derives to:

```text
NOT_STARTED
```

---

# 5. SchedulingStatus

Scheduling status is distinct from execution status.

It represents whether a task currently has a schedule placement.

```text
UNSCHEDULED
SCHEDULED
```

A task can therefore be:

```text
NOT_STARTED + UNSCHEDULED
NOT_STARTED + SCHEDULED
IN_PROGRESS + SCHEDULED
COMPLETED + UNSCHEDULED
...
```

The scheduler and planner treat these dimensions independently.

---

# 6. Composite Scheduling Status

Composite scheduling status is derived recursively.

Only child statuses:

```text
NOT_STARTED
IN_PROGRESS
```

are considered relevant for scheduling.

Terminal children are ignored:

```text
COMPLETED
CANCELLED
```

### Decision flow

```text
Composite
   │
   ▼
Find relevant children
   │
   ├── none
   │     └──► UNSCHEDULED
   │
   └── some
         │
         ├── all relevant children SCHEDULED
         │      └──► SCHEDULED
         │
         └── otherwise
                └──► UNSCHEDULED
```

Example:

```text
Parent
 ├── A = COMPLETED
 ├── B = CANCELLED
 ├── C = NOT_STARTED + SCHEDULED
 └── D = IN_PROGRESS + SCHEDULED

Parent = SCHEDULED
```

Because only C and D are relevant.

---

# 7. Dependency Execution Eligibility

`DependencyGraph.can_execute(task)` answers:

> Can this atomic task execute now?

Decision flow:

```text
Task
 │
 ├── not registered by exact identity? ──► False
 │
 ├── composite? ────────────────────────► False
 │
 ├── status != NOT_STARTED? ────────────► False
 │
 ├── any prerequisite != COMPLETED? ────► False
 │
 └── otherwise ─────────────────────────► True
```

`get_ready_tasks()` simply returns all registered tasks satisfying `can_execute()`.

---

# 8. Dependency Execution Order

`get_execution_order()` uses topological ordering.

Example:

```text
A ─► B ─► C
```

Execution order must satisfy:

```text
A before B before C
```

For a branching graph:

```text
A ──┐
    ├──► C
B ──┘
```

both A and B must occur before C.

If the graph contains a cycle, execution ordering fails with:

```text
Dependency graph contains a cycle.
```

---

# 9. CalendarEvent

A `CalendarEvent` represents an existing external commitment.

Important properties:

- Timezone-aware timestamps are required.
- Timestamps are normalized to UTC.
- `start < end`.
- Calendar events are considered non-changeable by the planner.

Calendar events consume available planning time.

Example:

```text
09:00 ───────────── 17:00  planning horizon

         Calendar Event
         11:00 ───── 13:00
```

Available time is therefore:

```text
09:00–11:00
13:00–17:00
```

---

# 10. TimeWindow

A `TimeWindow` represents usable continuous time.

Rules:

- Both timestamps must be timezone-aware.
- Timestamps are normalized to UTC.
- `start < end`.

A task must fit completely inside a single scheduling window.

---

# 11. Constraint

A `Constraint` contains:

```text
type
rule_information: TimeWindow
description
```

Constraint types include:

```text
HARD_CONSTRAINT
SOFT_CONSTRAINT
```

## Hard constraint

Removes time from availability.

```text
Planning horizon
      │
      ├── subtract calendar events
      │
      └── subtract hard constraints
               │
               ▼
        available TimeWindows
```

## Soft constraint

Does not remove time.

It only influences scheduler ranking.

---

# 12. Generating Available TimeWindows

`generate_time_windows()` performs:

```text
full planning interval
        │
        ▼
subtract calendar events
        │
        ▼
subtract hard constraints
        │
        ▼
clip intervals to planning horizon
        │
        ▼
sort intervals
        │
        ▼
merge overlapping/touching busy intervals
        │
        ▼
available TimeWindows
```

Soft constraints do not participate in this subtraction.

---

# 13. ScheduleBlock

A `ScheduleBlock` represents one concrete placement of an **atomic** task.

```text
Task A
09:00 → 10:00
```

Rules:

- Task cannot be `None`.
- Task must be atomic.
- Timestamps must be timezone-aware.
- Timestamps are normalized to UTC.
- `start < end`.

The scheduled duration comes from the scheduling candidate used to create the block.

---

# 14. SchedulingCandidate

A `SchedulingCandidate` wraps:

```text
task
duration
```

This is important for replanning.

A task might originally have:

```text
estimated duration = 2 hours
```

but after partial execution only:

```text
remaining work = 1 hour 15 minutes
```

The task remains the same object, while the candidate duration becomes:

```text
1h 15m
```

This allows the scheduler to place recovered work without mutating the task's estimated duration.

---

# 15. Plan

A `Plan` contains:

```text
id
date
planning_horizon
schedule_blocks
metadata
```

Plan invariants include:

- Non-empty plan ID.
- Positive planning horizon.
- Metadata is a dictionary of strings.
- Blocks must be atomic-task blocks.
- Blocks must lie inside the planning horizon.
- A task may not have multiple schedule blocks.
- Schedule blocks may not overlap.

---

# 16. Scheduler

The scheduler is responsible for placing eligible work into available windows.

Main flow:

```text
Tasks / SchedulingCandidates
          │
          ▼
evaluate_task_placement()
          │
          ▼
valid candidate placements
          │
          ▼
select_best_task_placement()
          │
          ▼
best block
          │
          ▼
consume_timewindow()
          │
          ▼
repeat
```

The scheduler does not mutate task state.

---

# 17. Scheduler Eligibility Decision

For each task:

```text
Task
 │
 ├── already scheduled?
 │       └──► ALREADY_SCHEDULED
 │
 ├── invalid task status?
 │       └──► INVALID_STATE
 │
 ├── composite?
 │       └──► INVALID_STATE
 │
 ├── duration <= 0?
 │       └──► INVALID_STATE
 │
 ├── no windows?
 │       └──► NO_AVAILABLE_WINDOW
 │
 ├── no window large enough?
 │       └──► INSUFFICIENT_TIME
 │
 └── otherwise
         ▼
      evaluate candidate placements
```

Recovered `SchedulingCandidate`s can represent `IN_PROGRESS` work.

---

# 18. Scheduler Candidate Start Decisions

For each fitting window, candidate starts are built from:

```text
window.start
```

plus relevant boundaries from:

```text
existing scheduled blocks
dependency completion times
soft-constraint preferred starts
```

The scheduler then rejects candidate starts that:

- Exceed the window.
- Violate dependency chronology.
- Overlap a supplied scheduled block.

---

# 19. Dependency-Aware Scheduling

For every prerequisite:

```text
if prerequisite.status == COMPLETED
    → no delay required

else
    prerequisite must have a scheduled block
    and its end must be <= dependent start
```

Example:

```text
A = 09:00–10:00
B depends on A
B window = 09:00–12:00
```

B cannot begin at 09:00.

Earliest legal start:

```text
10:00
```

Starting exactly when A ends is valid.

---

# 20. Multiple Prerequisites

Example:

```text
A = 09:00–10:00
B = 09:30–11:00
C depends on A and B
```

C must start no earlier than:

```text
max(A.end, B.end)
= 11:00
```

The scheduler derives the dependency start boundary from all prerequisites.

---

# 21. Soft Constraint Scheduling

A soft constraint is a preference rather than a hard boundary.

Example:

```text
Available: 09:00–13:00
Soft preference: 11:00–12:00
Task duration: 1 hour
```

A preferred candidate start is:

```text
11:00
```

If the soft preference window is too small:

```text
Preference: 11:00–11:30
Task duration: 1 hour
```

the task is still schedulable elsewhere.

---

# 22. Scheduler Ranking

Among valid candidate blocks, the scheduler considers:

```text
1. Soft-constraint satisfaction
2. Priority
3. Deadline
4. Start time
5. Duration
```

Priority ordering is:

```text
CRITICAL
HIGH
MEDIUM
LOW
```

Deadline is used for ranking, not as a hard placement boundary under the current contract.

---

# 23. TimeWindow Consumption

When a block is placed inside:

```text
09:00–13:00
```

the window is split depending on placement.

### Whole window consumed

```text
09:00–13:00
block: 09:00–13:00

remaining:
[]
```

### Beginning consumed

```text
window: 09:00–13:00
block: 09:00–10:00

remaining:
10:00–13:00
```

### End consumed

```text
window: 09:00–13:00
block: 12:00–13:00

remaining:
09:00–12:00
```

### Middle consumed

```text
window: 09:00–13:00
block: 11:00–12:00

remaining:
09:00–11:00
12:00–13:00
```

---

# 24. Scheduler Result

`SchedulingRunResult` contains:

```text
scheduled_blocks
unresolved_task_results
```

It also exposes sequence-like behavior for compatibility:

```text
iteration
len()
indexing
```

A run is complete when:

```text
unresolved_task_results == []
```

---

# 25. Observation

An `Observation` records an execution attempt against a concrete scheduled block.

It contains:

```text
task
scheduled_block
actual_start
actual_end
outcome
metadata
```

The observation must reference the exact same task object as the schedule block.

---

# 26. Observation Outcomes

Supported outcomes:

```text
COMPLETED
PARTIALLY_COMPLETED
CANCELLED
NOT_STARTED
```

---

# 27. Observation Validation

Each observation:

- Must have a task.
- Must have a schedule block.
- Must reference the exact same task object as the block.
- Must have non-null metadata.
- Must use timezone-aware timestamps.
- Timestamps are normalized to UTC.
- `actual_start < actual_end`.
- Outcome must be a valid observation enum.

---

# 28. Observation History

Observation history for one task must be:

```text
chronological
non-overlapping
terminal only at the end
```

Once execution has begun:

```text
NOT_STARTED
```

cannot appear later.

Likewise:

```text
COMPLETED
CANCELLED
```

cannot appear before another execution observation.

Example of valid history:

```text
PARTIALLY_COMPLETED
PARTIALLY_COMPLETED
COMPLETED
```

Invalid history:

```text
PARTIALLY_COMPLETED
NOT_STARTED
```

Invalid history:

```text
COMPLETED
PARTIALLY_COMPLETED
```

---

# 29. Observation → Task Status

`process_observation()` performs:

```text
validate transition
        │
        ▼
apply observation outcome
        │
        ▼
resolve scheduling status
```

The observation outcome changes the task's execution status according to the implemented domain mapping.

After processing, the observation resolves the task's scheduling status to:

```text
UNSCHEDULED
```

At the PlannerState level, scheduling status is then synchronized against the current plan when required.

---

# 30. Observation Transition Protection

A task that is already:

```text
COMPLETED
```

or:

```text
CANCELLED
```

cannot receive another observation.

Also:

```text
task.status == IN_PROGRESS
+
observation.outcome == NOT_STARTED
```

is rejected.

These checks prevent execution histories from moving backwards.

---

# 31. Observation Duration Calculations

For an observation:

```text
actual_duration = actual_end - actual_start
```

The domain also derives:

```text
start_delay
duration_difference
execution_deviation
remaining_duration
```

---

# 32. Remaining Work Calculation

The remaining work rules are:

```text
COMPLETED
    → 0

CANCELLED
    → 0

NOT_STARTED
    → full planned/estimated duration

PARTIALLY_COMPLETED
    → planned duration - actual partial work
      clamped to zero
```

Example:

```text
planned = 2h
partial observation = 45m

remaining = 1h 15m
```

Multiple partial observations accumulate productive work.

Example:

```text
planned = 2h

partial 1 = 30m
partial 2 = 45m

remaining = 45m
```

If productive work reaches or exceeds the planned duration:

```text
remaining = 0
```

---

# 33. RemainingWork

`RemainingWork` represents work recovered for rescheduling.

```text
task
duration
```

Its duration is positive.

It is used to create a:

```text
SchedulingCandidate
```

without changing the task's estimated duration.

---

# 34. PlannerState

`PlannerState` is the aggregate/source-of-truth for the planning domain.

It contains:

```text
goals
tasks
dependency_graph
calendar_events
constraints
current_plan
observations
```

---

# 35. PlannerState Identity Rules

Identity is important throughout the aggregate.

The following must refer to the exact task object:

```text
PlannerState.tasks
DependencyGraph.tasks
Goal.root_tasks
Observation.task
ScheduleBlock.task
dependency relationships
```

Equal values with a different Python object are not treated as the same domain entity.

Example:

```text
owned_task = Task(id="A", ...)
lookalike   = Task(id="A", ...)
```

Even though:

```text
owned_task.id == lookalike.id
```

the domain treats them as different objects.

---

# 36. PlannerState Constructor Invariants

PlannerState validates:

### Collections

```text
goals != None
tasks != None
dependency_graph != None
calendar_events != None
constraints != None
observations != None
```

Collections cannot contain `None`.

### Task IDs

Task IDs must be unique.

### Dependency graph ownership

Every PlannerState task must correspond to the exact same object in:

```text
dependency_graph.tasks
```

### Goals

- Goal IDs must be unique.
- Goal root tasks must belong to PlannerState.
- Root tasks must not have parents.
- Root tasks must be registered in the dependency graph.
- Duplicate roots are rejected.
- One task cannot be a root of multiple Goals.

### Observations

Every observation task must be owned by PlannerState.

Observation histories are validated.

### Current plan

Current plan scheduling statuses must match the plan.

---

# 37. PlannerState Plan/Scheduling Consistency

When there is no current plan:

```text
every task.scheduling_status
    must be UNSCHEDULED
```

When there is a current plan:

```text
task appears in plan
    → scheduling_status = SCHEDULED

task does not appear in plan
    → scheduling_status = UNSCHEDULED
```

The plan is also rejected when:

- A scheduled task is outside PlannerState.
- A completed task is scheduled.
- A cancelled task is scheduled.
- Dependency chronology is violated.

---

# 38. PlannerState Task Removal

A task cannot be removed if:

```text
it has a parent
it has children
it has dependency relationships
it is a Goal root
it has observations
it is scheduled, unless removal is being committed through replanning
```

Normal unscheduled removal:

```text
validate
  ↓
unregister from DependencyGraph
  ↓
remove exact task from PlannerState.tasks
```

Scheduled removal follows the staged replanning flow.

---

# 39. PlannerState Observation Flow

`record_observation()`:

```text
Observation
    │
    ▼
add_observation()
    │
    ▼
validate history/transition
    │
    ▼
store observation
    │
    ▼
process observation
    │
    ▼
task status changes
    │
    ▼
scheduling status resolved
    │
    ▼
synchronize_task_states()
```

This also updates relevant composite task state.

---

# 40. PlannerState Dependency Flow

Adding a dependency:

```text
PlannerState.add_dependency()
        │
        ▼
verify both tasks are state-owned
        │
        ▼
DependencyGraph.add_dependency()
        │
        ├── self-dependency?
        ├── duplicate?
        ├── same task tree?
        └── cycle?
        │
        ▼
edge added
```

Removing a dependency follows the corresponding validation and graph removal logic.

---

# 41. PlanningChange

`PlanningChange` tells the replanner what changed.

Supported categories include:

```text
TASK_ADDED
TASK_UPDATED
TASK_REMOVED

CALENDAR_EVENT_ADDED
CALENDAR_EVENT_UPDATED
CALENDAR_EVENT_REMOVED

CONSTRAINT_ADDED
CONSTRAINT_UPDATED
CONSTRAINT_REMOVED

DEPENDENCY_ADDED
DEPENDENCY_REMOVED

OBSERVATION_RECORDED

PLAN_REPLACED
```

---

# 42. PlanningChange State Contract

The key rule is:

> The PlannerState should already reflect the change before `replan()` runs.

The exception is:

```text
TASK_REMOVED
```

The removed task remains temporarily present so the replacement plan can be calculated and the actual removal can be committed atomically with the new plan.

---

# 43. Task Change Impact

For:

```text
TASK_ADDED
TASK_UPDATED
TASK_REMOVED
```

the planner identifies the changed task and its transitive dependents where the graph still owns the task.

Impact propagation:

```text
A changes
 │
 └──► dependents of A
          │
          └──► dependents of those tasks
```

A task update can be ignored for planning purposes when `changed_fields` only contain non-scheduling metadata such as:

```text
title
description
```

Scheduling-relevant fields include:

```text
priority
estimated_duration
deadline
status
scheduling_status
```

---

# 44. Observation Change Impact

When an observation is recorded:

```text
observed task
      │
      ▼
observed task + all transitive dependents
```

are considered impacted because the task's execution state/remaining work may affect downstream planning.

---

# 45. Dependency Change Impact

## Dependency added

```text
dependent
    │
    └──► all transitive dependents
```

are impacted.

The newly added prerequisite can change legal chronology.

## Dependency removed

Existing valid placements are preserved.

Removal relaxes a constraint and can free unscheduled work to be considered again.

---

# 46. Resource Change Impact

Resource changes include:

```text
CalendarEvent
Constraint
```

### Calendar event added/updated

Any scheduled block overlapping the new/updated event is invalidated.

### Calendar event removed

Existing valid blocks are not invalidated.

Previously blocked time becomes available for unscheduled work.

### Hard constraint added/updated

Overlapping scheduled blocks are invalidated.

### Hard constraint removed

Existing valid blocks are preserved and newly available time can be used.

### Soft constraint added/updated

It does not directly invalidate blocks; it changes scheduling preference.

### Soft constraint removed

It does not invalidate blocks.

---

# 47. Resource Invalidation + Dependencies

When a prerequisite block becomes invalid because of a resource change:

```text
invalidated prerequisite A
        │
        ▼
dependent B
        │
        ▼
dependent C
```

scheduled transitive dependents are also invalidated so the resulting plan cannot retain dependency chronology that is no longer valid.

---

# 48. Invalidated Blocks

`invalidated_blocks()` identifies blocks whose tasks are affected.

It does not itself mutate the plan.

Output:

```text
old plan blocks that must be reconsidered
```

---

# 49. Preserved Blocks

`preserve_blocks()` returns:

```text
old plan blocks
    minus invalidated blocks
```

These blocks remain part of the new proposed plan.

---

# 50. Rebuilding Available Windows During Replanning

The replanner reconstructs availability from the current PlannerState:

```text
planning_start → planning_end
        │
        ▼
calendar events
        │
        ▼
hard constraints
        │
        ▼
base available windows
        │
        ▼
subtract preserved blocks
        │
        ▼
windows available for recovered work
```

---

# 51. Replanning Remaining Work

For every task being reconsidered:

```text
task
 │
 ├── COMPLETED/CANCELLED?
 │       └── no remaining work
 │
 ├── no observations?
 │       └── estimated duration
 │
 └── observations?
         └── calculate history
                 │
                 ▼
             remaining work
```

Remaining work is converted into scheduling candidates.

---

# 52. Replanning Existing Plan

When `current_plan` exists:

```text
old plan
   │
   ▼
calculate invalidated blocks
   │
   ▼
preserve unaffected blocks
   │
   ▼
recover remaining work from invalidated tasks
   │
   ▼
possibly add new/eligible work
   │
   ▼
rebuild available windows
   │
   ▼
schedule remaining work
   │
   ▼
merge preserved + new blocks
   │
   ▼
build new Plan
```

The old plan itself is not mutated.

---

# 53. Replanning Without an Existing Plan

When:

```text
current_plan is None
```

the replanner considers eligible atomic work directly.

Eligible states include:

```text
NOT_STARTED
IN_PROGRESS
```

Completed and cancelled work is ignored.

The result is a new Plan, even though there was no old plan.

---

# 54. Newly Added Task

A newly added atomic task has no old schedule block to invalidate.

The replanner therefore includes it directly as remaining work when eligible:

```text
TASK_ADDED
    │
    ▼
atomic?
    │
    ├── no → not directly scheduled
    │
    └── yes
         │
         ▼
NOT_STARTED / IN_PROGRESS?
         │
         ▼
RemainingWork(task, estimated_duration)
         │
         ▼
scheduler
```

---

# 55. Unscheduled Work Reconsideration

Some changes can create newly available planning opportunities.

These include:

```text
CALENDAR_EVENT_UPDATED
CALENDAR_EVENT_REMOVED
CONSTRAINT_ADDED
CONSTRAINT_UPDATED
CONSTRAINT_REMOVED
DEPENDENCY_REMOVED
```

For these changes, other currently unscheduled eligible atomic tasks may also be reconsidered.

This allows newly available time to be filled without invalidating unrelated valid blocks.

---

# 56. Partial Observation Replanning

Example:

```text
Original task estimate:
2h

Old block:
09:00–11:00

Actual work:
09:00–09:45

Outcome:
PARTIALLY_COMPLETED
```

Remaining work:

```text
2h - 45m = 1h 15m
```

Replanning therefore creates a scheduling candidate of:

```text
1h 15m
```

The task itself remains the same task object.

---

# 57. Terminal Observation Replanning

If observation outcome is:

```text
COMPLETED
```

or:

```text
CANCELLED
```

remaining work becomes zero.

The existing scheduled block is invalidated/removed from the active plan during replanning.

No replacement block is scheduled.

---

# 58. Task Priority Update

For:

```text
TASK_UPDATED
changed_fields={"priority"}
```

the old block is invalidated.

The task is recovered as remaining work and scheduled again using its updated priority.

Unrelated scheduled tasks can remain preserved.

---

# 59. Task Duration Update

For:

```text
changed_fields={"estimated_duration"}
```

the old block is invalidated.

The task is rescheduled with the new duration.

Example:

```text
old = 1h
new = 2h
```

The replacement block uses:

```text
2h
```

---

# 60. Task Deadline Update

A deadline update causes the task to be reconsidered.

The deadline influences candidate ranking/order.

Under the current domain contract, it is **not** itself a hard scheduling boundary.

---

# 61. Calendar Event Added

Example:

```text
Old block:
11:00–12:00

New event:
11:30–13:00
```

The block overlaps the new event.

Decision:

```text
overlap?
   └── yes → invalidate block
```

Unrelated blocks remain preserved.

The task from the invalidated block is recovered and rescheduled into the remaining available windows.

---

# 62. Calendar Event Updated

The event object already contains the post-update interval before `replan()`.

The replanner therefore uses:

```text
new event interval
```

when calculating invalidation.

It does not rely on the previous event interval.

---

# 63. Calendar Event Removed

Removing an event does not invalidate valid existing blocks.

Instead:

```text
removed event
     │
     ▼
new free time
     │
     ▼
reconsider eligible unscheduled work
```

---

# 64. Hard Constraint Added

Any block overlapping the new hard constraint is invalidated.

The task can then be scheduled outside that hard-constrained period.

---

# 65. Hard Constraint Removed

Existing blocks remain preserved.

The newly free period may be used by currently unscheduled work.

---

# 66. Soft Constraint Added

A soft constraint:

```text
does not remove availability
does not force invalidation
```

It changes candidate scoring.

Example:

```text
available = 09:00–13:00
soft preference = 11:00–12:00
```

A one-hour task is preferentially placed at 11:00.

---

# 67. Dependency Added During Replanning

Suppose:

```text
A = 10:00–11:00
B = 09:00–10:00
```

and a new dependency is added:

```text
B depends on A
```

B's old block is now chronologically invalid.

Decision:

```text
dependency added
      │
      ▼
dependent impacted
      │
      ▼
old dependent block invalidated
      │
      ▼
recover B
      │
      ▼
preserve A if still valid
      │
      ▼
reschedule B after A
```

Transitive dependents are also considered.

---

# 68. Dependency Added With a Completed Prerequisite

If prerequisite A is already:

```text
COMPLETED
```

then B does not need a scheduled A block.

So B may begin at the normal earliest available point.

---

# 69. Dependency Added With No Valid Slot

A dependent may become impossible to place because the prerequisite consumes the remaining time.

Example:

```text
A must finish at 11:00
B requires 1h
planning ends at 11:30
```

Then:

```text
B remaining work = 1h
B has no legal slot
```

The result contains:

```text
unresolved_work = B / 1h
```

rather than an invalid placement.

---

# 70. Dependency Removed During Replanning

Removing:

```text
B depends on A
```

does not invalidate a schedule that is already valid.

Instead:

```text
dependency removed
       │
       ▼
existing valid blocks preserved
       │
       ▼
dependency constraint relaxed
       │
       ▼
other unscheduled work may be reconsidered
```

---

# 71. Replanning Result

`ReplanningResult` is the immutable proposal produced by `replan()`.

It contains:

```text
new_plan
preserved_blocks
invalidated_blocks
rescheduled_blocks
unresolved_work
removed_tasks
```

---

# 72. ReplanningResult Integrity Rules

The result validates that:

### Plan

```text
new_plan exists
```

### Collections

```text
not None
no None elements
```

### Blocks

Blocks across:

```text
preserved
invalidated
rescheduled
```

cannot be duplicated by identity.

### Preserved blocks

Must appear in the new plan.

### Invalidated blocks

Must not appear in the new plan.

### Rescheduled blocks

Must appear in the new plan.

### Terminal work

Completed/cancelled tasks cannot be scheduled.

### Removed tasks

Removed tasks cannot appear in the new plan.

### Unresolved work

- Cannot contain duplicate task objects.
- Must have positive duration.
- Cannot belong to completed/cancelled tasks.
- Cannot simultaneously appear in the new plan.

---

# 73. Replanning Purity

`replan()` is a proposal-calculation operation.

Before:

```text
PlannerState
```

During:

```text
read state
calculate invalidation
recover work
schedule candidates
build result
```

After:

```text
PlannerState remains unchanged
```

The only exception is that the state is expected to already reflect the external change before replanning begins.

For task removal, the task remains staged in state until commit.

---

# 74. Atomic Apply Flow

`apply_replanning_result()` delegates to:

```text
PlannerState.commit_replanned_plan()
```

The commit operation validates everything before mutation.

Conceptually:

```text
ReplanningResult
      │
      ▼
validate task hierarchy
      │
      ▼
validate removed tasks
      │
      ▼
validate new plan
      │
      ▼
validate ownership
      │
      ▼
validate atomic tasks
      │
      ▼
validate dependency chronology
      │
      ▼
validate scheduling consistency
      │
      ▼
ONLY NOW mutate
```

This provides the atomic boundary.

---

# 75. Atomic Commit — Successful Case

```text
old PlannerState
      │
      ▼
apply valid result
      │
      ├── remove staged tasks
      │
      ├── update scheduling statuses
      │
      ├── replace current_plan
      │
      └── synchronize composite states
```

The resulting PlannerState becomes internally consistent.

---

# 76. Atomic Commit — Failure Case

If any validation fails:

```text
invalid result
      │
      ▼
validation error
      │
      ▼
NO mutation
```

The following must remain unchanged:

```text
current_plan
tasks
dependency graph
task scheduling statuses
staged removal membership
```

This is the core #088 guarantee.

---

# 77. Staged Scheduled Task Removal

A scheduled task cannot simply disappear immediately.

Flow:

```text
TASK_REMOVED
    │
    ▼
task remains in PlannerState
    │
    ▼
replan()
    │
    ├── invalidate its block
    ├── exclude it from new plan
    └── add task to removed_tasks
    │
    ▼
ReplanningResult
    │
    ▼
apply
    │
    ▼
atomic commit
    │
    ├── unregister task from dependency graph
    ├── remove task from PlannerState
    └── install replacement plan
```

If commit fails, the task remains present.

---

# 78. Direct Unscheduled Task Removal

An unscheduled task can be removed directly when all removal invariants pass:

```text
not scheduled
no parent
no children
no dependencies
not a Goal root
no observations
```

Then:

```text
DependencyGraph.unregister_task()
        ↓
PlannerState.tasks removal
```

---

# 79. Invalid Plan Protection

A replacement plan is rejected if it contains:

```text
outside task
completed task
cancelled task
duplicate task block
overlapping block
out-of-horizon block
dependency chronology violation
```

The old state remains unchanged.

---

# 80. End-to-End Planning Workflow

The complete domain planning workflow is:

```text
                ┌──────────────────┐
                │ PlannerState     │
                └────────┬─────────┘
                         │
                         ▼
                 PlanningChange
                         │
                         ▼
                 validate state
                         │
                         ▼
               calculate impact
                         │
                         ▼
              invalidate old blocks
                         │
                         ▼
                 preserve others
                         │
                         ▼
              recover remaining work
                         │
                         ▼
              rebuild available windows
                         │
                         ▼
                 schedule candidates
                         │
                         ▼
              unresolved work?
                  /             \
                yes             no
                 │               │
                 ▼               ▼
          retain RemainingWork
                         │
                         ▼
              merge schedule blocks
                         │
                         ▼
                 build new Plan
                         │
                         ▼
              build ReplanningResult
                         │
                         ▼
             ───── proposal only ─────
                         │
                         ▼
             apply_replanning_result()
                         │
                         ▼
              atomic validation
                         │
                    ┌────┴────┐
                  fail       pass
                   │           │
                   ▼           ▼
             state unchanged  commit
                               │
                               ▼
                         new PlannerState
```

---

# 81. Major Decision Flows Summary

## A. "Can this task execute?"

```text
registered by identity?
        ↓ yes
atomic?
        ↓ yes
NOT_STARTED?
        ↓ yes
all prerequisites COMPLETED?
        ↓ yes
      EXECUTABLE
```

## B. "Can this task be scheduled?"

```text
eligible state?
        ↓
atomic?
        ↓
positive duration?
        ↓
fitting window?
        ↓
dependency chronology valid?
        ↓
no overlap?
        ↓
valid placement
```

## C. "Should an old block be invalidated?"

```text
task/observation/dependency/resource impact?
        │
        ├── no → preserve
        │
        └── yes
              ↓
          invalidate
```

## D. "How much work is left?"

```text
COMPLETED/CANCELLED → 0

NOT_STARTED → estimated/planned duration

PARTIALLY_COMPLETED
    → planned duration
      - accumulated partial work
      → clamp to zero
```

## E. "Can the composite task be COMPLETED?"

```text
derive all descendants
        │
        ├── any BLOCKED → BLOCKED
        ├── any IN_PROGRESS → IN_PROGRESS
        ├── any CANCELLED → IN_PROGRESS
        ├── all COMPLETED → COMPLETED
        └── otherwise → NOT_STARTED / IN_PROGRESS
```

## F. "Should composite scheduling be SCHEDULED?"

```text
ignore COMPLETED/CANCELLED children
        │
        ├── no relevant children → UNSCHEDULED
        │
        ├── all relevant children scheduled → SCHEDULED
        │
        └── otherwise → UNSCHEDULED
```

## G. "Can a replanning result be committed?"

```text
result structurally valid?
        ↓
removed tasks valid?
        ↓
tasks owned by PlannerState?
        ↓
plan valid?
        ↓
blocks valid?
        ↓
dependencies valid?
        ↓
scheduling status consistent?
        ↓
       COMMIT
```

Any failure before the final step means:

```text
NO STATE MUTATION
```

---

# 82. Invariants by Responsibility

| Responsibility | Main owner |
|---|---|
| Goal/root-task ownership | `Goal`, `PlannerState` |
| Parent/child hierarchy | `Task`, `PlannerState` |
| Dependency edges | `DependencyGraph` |
| Dependency cycle detection | `DependencyGraph` |
| Execution eligibility | `DependencyGraph` |
| Time interval validity | `TimeWindow`, `CalendarEvent`, `ScheduleBlock` |
| Hard availability | `generate_time_windows()` |
| Soft preference scoring | Scheduler |
| Schedule placement | Scheduler |
| Plan structural validity | `Plan` |
| Execution history | `Observation` |
| Remaining work | Observation history helpers |
| Aggregate consistency | `PlannerState` |
| Change impact | Replanning layer |
| Proposed replacement plan | `replan()` |
| Result integrity | `ReplanningResult` |
| Atomic state transition | `PlannerState.commit_replanned_plan()` |

---

# 83. Architectural Boundary

The completed domain layer can be viewed as five cooperating areas:

```text
1. Work Model
   Goal
   Task

2. Dependency Model
   DependencyGraph

3. Time & Schedule Model
   CalendarEvent
   Constraint
   TimeWindow
   ScheduleBlock
   Plan
   Scheduler

4. Execution Model
   Observation
   Observation history
   RemainingWork

5. Planning/Replanning Model
   PlannerState
   PlanningChange
   ReplanningResult
   replan()
   atomic commit
```

The central architectural principle is:

```text
Task hierarchy != dependency graph
Execution status != scheduling status
Calculation != mutation
Proposal != commit
```

---

# 84. Domain Layer Completion Boundary

For the implemented scope, the domain layer ends after:

```text
Goal
Task
DependencyGraph
CalendarEvent
TimeWindow
Constraint
ScheduleBlock
SchedulingCandidate
Plan
Observation
Observation history
PlannerState
PlanningChange
RemainingWork
ReplanningResult
Scheduler
Replanner
Atomic result application
```

The next application-level layer should consume these domain operations rather than moving HTTP, database, notification, or UI concerns into them.

---

# 85. Test Coverage Milestone

The completed implementation was validated with:

```text
149 passed
0 diagnostics
```

The tests cover the implemented domain behavior including:

- Task hierarchy invariants.
- Dependency graph invariants and DAG ordering.
- Scheduler placement and hardening.
- Dependency-aware scheduling.
- Soft-constraint behavior.
- Observation lifecycle.
- Remaining-work recovery.
- Composite task state.
- PlannerState invariants.
- Identity semantics.
- Plan/state consistency.
- Replanning impact.
- Replanning result integrity.
- Replanning purity.
- Atomic result application.