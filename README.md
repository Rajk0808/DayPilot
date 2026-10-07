# DayPilot

DayPilot is a personal task-planning engine designed to turn tasks, constraints, dependencies, calendar commitments, and execution feedback into an adaptive daily plan.

The project is being built from the inside out:

```text
Interfaces
    ↓
Application
    ↓
Domain
    ↓
Persistence
    ↓
Infrastructure
```

The **Domain Layer** and **Application Layer** are currently complete for the implemented scope. The next major phase is Persistence.

---

# Project Status

| Phase | Status |
|---|---|
| Domain Layer | ✅ Complete |
| Application Layer | ✅ Complete |
| Persistence Layer | 🚧 Next |
| Infrastructure Layer | ⏳ Planned |
| Interface / API Layer | ⏳ Planned |
| External Integrations | ⏳ Planned |

Current validation baseline:

```text
248 tests passed
0 diagnostics
```

---

# Architecture

DayPilot separates **business rules** from **use-case orchestration**.

```text
External Interface
       │
       ▼
┌──────────────────────────┐
│ Application Layer        │
│                          │
│ Use cases + orchestration│
└────────────┬─────────────┘
             │
             ▼
┌──────────────────────────┐
│ Domain Layer             │
│                          │
│ Rules + invariants +     │
│ scheduling + replanning  │
└────────────┬─────────────┘
             │
             ▼
┌──────────────────────────┐
│ Persistence / Infra      │
│                          │
│ DB + external services   │
└──────────────────────────┘
```

The application layer follows the central rule:

```text
Application = orchestration
Domain      = decisions and invariants
```

An application service should coordinate domain operations but should not reproduce domain logic such as dependency-cycle detection, schedule ranking, remaining-work calculation, hierarchy validation, or plan validation.

---

# Domain Layer

The domain layer contains the core planning model and business rules.

It includes:

```text
Goal
Task
DependencyGraph

CalendarEvent
Constraint
TimeWindow

ScheduleBlock
SchedulingCandidate
Plan

Observation
RemainingWork

PlannerState
PlanningChange
ReplanningResult
Scheduler
Replanner
```

The central domain principles are:

```text
Task hierarchy != dependency graph

Execution status != scheduling status

Calculation != mutation

Proposal != commit
```

Detailed domain documentation:

→ [Domain Model](domain.md)

---

# Application Layer

The application layer exposes concrete use cases around the domain.

It coordinates:

```text
validate application input
        ↓
verify aggregate ownership / identity
        ↓
perform the required domain mutation
        ↓
create PlanningChange when planning is affected
        ↓
calculate replanning proposal
        ↓
atomically commit the proposal
        ↓
return the application result
```

Not every use case triggers replanning.

There are two categories:

```text
Planning-affecting use cases
    → mutate state
    → PlanningChange
    → replan()
    → apply_replanning_result()

Non-planning use cases
    → mutate state through PlannerState/domain operation
    → return
```

---

# Application Layer Structure

```text
src/daypilot/application/
│
├── task_service.py
├── goal_service.py
├── dependency_service.py
├── calendar_service.py
├── constraint_service.py
├── observation_service.py
├── hierarchy_service.py
├── planning_service.py
└── application_service.py
```

The classes are:

```text
TaskApplicationService
GoalApplicationService
DependencyApplicationService
CalendarApplicationService
ConstraintApplicationService
ObservationApplicationService
TaskHierarchyApplicationService
PlanningApplicationService
DayPilotApplicationService
```

---

# 1. TaskApplicationService

File:

```text
src/daypilot/application/task_service.py
```

The task service owns task-level application workflows.

It currently exposes:

```text
create_task()
change_task()
remove_task()
```

Supporting request model:

```text
TaskCreateRequest
TaskUpdateRequest
```

---

## 1.1 `create_task()`

### Purpose

Create a new task, register it in the PlannerState, replan around the new work, and atomically commit the resulting plan.

### Flow

```text
TaskCreateRequest
        ↓
validate state/request/planning window
        ↓
construct Task
        ↓
PlannerState.add_task()
        ↓
PlanningChange(TASK_ADDED)
        ↓
replan()
        ↓
apply_replanning_result()
        ↓
return ReplanningResult
```

### Domain boundary

The application service does not decide whether the task is schedulable.

The domain decides:

```text
atomic vs composite
task status
available windows
constraints
dependencies
duration
priority
deadline
```

### Failure handling

Because the task is registered before replanning:

```text
state.add_task(task)
        ↓
replan/apply fails
        ↓
state.remove_task(task)
        ↓
re-raise original exception
```

The newly created task must not remain partially registered after a failed use case.

### Result

Returns:

```text
ReplanningResult
```

which allows the caller to see:

```text
new plan
preserved blocks
invalidated blocks
rescheduled blocks
unresolved work
removed tasks
```

---

## 1.2 `change_task()`

### Purpose

Change task properties and, when appropriate, recompute the plan.

Supported application update fields are controlled explicitly by the service, for example:

```text
title
description
priority
estimated_duration
deadline
status
```

### Flow

```text
TaskUpdateRequest
        ↓
validate request/state/time
        ↓
verify exact task identity
        ↓
determine changed_fields
        ↓
reject empty update
        ↓
capture original values
        ↓
apply requested values
        ↓
PlanningChange(TASK_UPDATED)
        ↓
replan()
        ↓
apply_replanning_result()
        ↓
return ReplanningResult
```

### Planning impact

The service itself does not decide whether a field affects planning.

It records:

```text
changed_fields
```

and delegates planning impact to the domain.

Current scheduling-relevant task fields include:

```text
priority
estimated_duration
deadline
status
scheduling_status
```

Metadata-only changes such as:

```text
title
description
```

do not cause planning invalidation under the current domain contract.

### Failure handling

```text
task mutated
     ↓
replan/apply fails
     ↓
restore original task values
     ↓
re-raise
```

The application layer therefore prevents a failed use case from leaving the task mutation behind.

### Identity

The task must be the exact object owned by PlannerState:

```python
any(existing is task for existing in state.tasks)
```

An equal-valued task with the same ID is not considered the same entity.

---

## 1.3 `remove_task()`

### Purpose

Remove a task while respecting the domain's staged-removal model.

### Flow

```text
validate state/task/planning window
        ↓
verify exact task identity
        ↓
PlanningChange(TASK_REMOVED)
        ↓
replan()
        ↓
ReplanningResult.removed_tasks
        ↓
apply_replanning_result()
        ↓
atomic removal + new plan
```

The task is intentionally **not manually removed before replanning**.

The domain commit handles:

```text
PlannerState.tasks
DependencyGraph
current_plan
scheduling_status
```

as one atomic operation.

### Why no application rollback is required

```text
replan()
    = pure proposal

apply_replanning_result()
    = atomic commit
```

So a failed replan leaves the task untouched, while a failed commit leaves the aggregate unchanged.

---

# 2. GoalApplicationService

File:

```text
src/daypilot/application/goal_service.py
```

The goal service owns Goal lifecycle operations:

```text
create_goal()
change_goal()
remove_goal()
```

Supporting request model:

```text
GoalUpdateRequest
```

Goal changes currently do **not** trigger replanning because the implemented domain does not model Goal updates as schedule-affecting `PlanningChange` events.

---

## 2.1 `create_goal()`

### Flow

```text
Goal
  ↓
validate state/Goal
  ↓
verify identity rules
  ↓
PlannerState.add_goal()
  ↓
return Goal
```

No replanning is performed.

The domain remains responsible for:

```text
unique Goal IDs
root-task ownership
Goal/task consistency
```

---

## 2.2 `change_goal()`

### Purpose

Update mutable Goal metadata through the aggregate boundary.

Typical update fields:

```text
title
description
deadline
status
```

### Flow

```text
GoalUpdateRequest
        ↓
validate state/request
        ↓
verify exact Goal identity
        ↓
determine changed_fields
        ↓
reject empty update
        ↓
PlannerState.update_goal()
        ↓
return updated Goal
```

### Current planning rule

```text
Goal metadata change
        ↓
no PlanningChange
        ↓
no automatic replanning
```

This is an explicit current-domain decision.

If Goal metadata later becomes a scheduling input, that should be introduced as a domain change first rather than hidden inside the application service.

---

## 2.3 `remove_goal()`

### Flow

```text
validate state/Goal
        ↓
verify exact Goal identity
        ↓
PlannerState.remove_goal()
        ↓
return
```

The service does not duplicate Goal-removal rules.

The domain decides whether Goal removal is valid based on its current root-task and ownership invariants.

---

# 3. DependencyApplicationService

File:

```text
src/daypilot/application/dependency_service.py
```

Exposes:

```text
add_dependency()
remove_dependency()
```

Dependencies are planning-affecting operations.

---

## 3.1 `add_dependency()`

### Flow

```text
validate state/tasks/planning window
        ↓
verify exact dependent identity
        ↓
verify exact prerequisite identity
        ↓
PlannerState.add_dependency()
        ↓
PlanningChange(DEPENDENCY_ADDED)
        ↓
replan()
        ↓
apply_replanning_result()
        ↓
return ReplanningResult
```

The domain decides:

```text
self-dependency
duplicate edge
same-tree dependency
cycle
dependency chronology
```

### Failure handling

The dependency is mutated before replanning:

```text
add dependency
      ↓
replan/apply failure
      ↓
remove dependency
      ↓
re-raise
```

The application service therefore treats the dependency mutation and planning operation as one use case.

---

## 3.2 `remove_dependency()`

### Flow

```text
validate state/tasks/planning window
        ↓
verify exact task identities
        ↓
verify edge exists
        ↓
PlannerState.remove_dependency()
        ↓
PlanningChange(DEPENDENCY_REMOVED)
        ↓
replan()
        ↓
apply_replanning_result()
        ↓
return ReplanningResult
```

### Failure handling

```text
remove dependency
      ↓
replan/apply failure
      ↓
add dependency back
      ↓
re-raise
```

### Domain distinction

Dependency removal and addition have different planning consequences:

```text
DEPENDENCY_ADDED
    → can invalidate dependent schedule blocks

DEPENDENCY_REMOVED
    → does not invalidate an already-valid placement
    → can free previously unschedulable work
```

The application service does not implement that distinction; the domain does.

---

# 4. CalendarApplicationService

File:

```text
src/daypilot/application/calendar_service.py
```

Exposes:

```text
add_event()
update_event()
remove_event()
```

Supporting request model:

```text
CalendarEventUpdateRequest
```

---

## 4.1 `add_event()`

### Flow

```text
validate state/event/planning window
        ↓
reject exact duplicate event identity
        ↓
PlannerState.add_calendar_event()
        ↓
PlanningChange(CALENDAR_EVENT_ADDED)
        ↓
replan()
        ↓
apply_replanning_result()
        ↓
return ReplanningResult
```

### Failure handling

```text
event added
    ↓
failure
    ↓
remove event
    ↓
re-raise
```

Calendar-event overlap and task invalidation remain domain/replanner responsibilities.

---

## 4.2 `update_event()`

### Purpose

Update the existing CalendarEvent while using the **post-update event interval** for replanning.

### Flow

```text
CalendarEventUpdateRequest
        ↓
validate ownership
        ↓
determine changed_fields
        ↓
reject empty update
        ↓
build proposed values
        ↓
validate proposed event
        ↓
capture original values
        ↓
mutate existing event
        ↓
PlanningChange(CALENDAR_EVENT_UPDATED)
        ↓
replan()
        ↓
apply_replanning_result()
        ↓
return ReplanningResult
```

### Failure handling

```text
event changed
    ↓
replan/apply fails
    ↓
restore original event values
    ↓
re-raise
```

### Important semantic

The change object points to the same event object after its values have been updated.

Therefore the replanner works against:

```text
post-change start
post-change end
```

rather than the previous event interval.

---

## 4.3 `remove_event()`

### Flow

```text
validate ownership
        ↓
PlannerState.remove_calendar_event()
        ↓
PlanningChange(CALENDAR_EVENT_REMOVED)
        ↓
replan()
        ↓
apply_replanning_result()
        ↓
return ReplanningResult
```

Failure:

```text
removed event
    ↓
failure
    ↓
add event back
    ↓
re-raise
```

Removing a calendar event does not directly invalidate already-valid schedule blocks; it may create newly available time for unscheduled work.

---

# 5. ConstraintApplicationService

File:

```text
src/daypilot/application/constraint_service.py
```

Exposes:

```text
add_constraint()
update_constraint()
remove_constraint()
```

Supporting request model:

```text
ConstraintUpdateRequest
```

---

## 5.1 `add_constraint()`

### Flow

```text
validate state/constraint/planning window
        ↓
PlannerState.add_constraint()
        ↓
PlanningChange(CONSTRAINT_ADDED)
        ↓
replan()
        ↓
apply_replanning_result()
        ↓
return ReplanningResult
```

Failure:

```text
constraint added
    ↓
failure
    ↓
remove constraint
    ↓
re-raise
```

### Hard vs soft

The application service does not choose the scheduling semantics.

The domain decides:

```text
HARD_CONSTRAINT
    → removes availability
    → can invalidate overlapping blocks

SOFT_CONSTRAINT
    → affects candidate preference
    → does not inherently make a task unschedulable
```

---

## 5.2 `update_constraint()`

### Flow

```text
ConstraintUpdateRequest
        ↓
validate ownership
        ↓
determine changed_fields
        ↓
reject empty update
        ↓
build proposed values
        ↓
construct/validate proposed Constraint
        ↓
capture original values
        ↓
mutate existing Constraint
        ↓
PlanningChange(CONSTRAINT_UPDATED)
        ↓
replan()
        ↓
apply_replanning_result()
        ↓
return ReplanningResult
```

### Failure handling

```text
constraint changed
    ↓
failure
    ↓
restore original values
    ↓
re-raise
```

### Proposed-state validation

The new Constraint is validated **before** mutating the state-owned object, preventing the aggregate from entering an invalid intermediate state.

---

## 5.3 `remove_constraint()`

### Flow

```text
validate ownership
        ↓
PlannerState.remove_constraint()
        ↓
PlanningChange(CONSTRAINT_REMOVED)
        ↓
replan()
        ↓
apply_replanning_result()
        ↓
return ReplanningResult
```

Failure:

```text
constraint removed
    ↓
failure
    ↓
add constraint back
    ↓
re-raise
```

Removing a hard constraint can create newly available time without inherently invalidating valid existing blocks.

---

# 6. ObservationApplicationService

File:

```text
src/daypilot/application/observation_service.py
```

Exposes:

```text
record_observation()
```

Supporting request model:

```text
ObservationRequest
```

Observation is intentionally a **record-only** lifecycle in the current domain.

There is no generic:

```text
update_observation()
remove_observation()
```

because observations represent execution history and are governed by chronological/non-overlapping/terminal history rules.

---

## 6.1 `record_observation()`

### Flow

```text
ObservationRequest
        ↓
validate state/request/planning window
        ↓
verify exact task identity
        ↓
snapshot relevant task state
        ↓
construct Observation
        ↓
PlannerState.record_observation()
        ↓
PlanningChange(OBSERVATION_RECORDED)
        ↓
replan()
        ↓
apply_replanning_result()
        ↓
return ReplanningResult
```

### Domain responsibilities

The application service does not calculate:

```text
actual duration
remaining work
task status
composite status
observation-history validity
```

Those remain domain responsibilities.

### Failure handling

Observation recording changes multiple observable pieces of state:

```text
observation history
task status
task scheduling status
composite ancestor states
```

Therefore the service captures the pre-operation task states.

If replanning or commit fails:

```text
remove exact recorded observation
        ↓
restore task statuses
        ↓
restore scheduling statuses
        ↓
re-raise
```

The result is intended to be all-or-nothing from the application caller's perspective.

---

# 7. TaskHierarchyApplicationService

File:

```text
src/daypilot/application/hierarchy_service.py
```

Exposes:

```text
add_child()
remove_child()
```

Hierarchy changes currently do **not** trigger replanning.

---

## 7.1 `add_child()`

### Flow

```text
validate state
        ↓
verify exact parent identity
        ↓
verify exact child identity
        ↓
PlannerState.add_child_task()
        ↓
return
```

The service does not manually modify:

```text
parent.children
child.parent
```

The domain owns:

```text
self-cycle
descendant cycle
existing parent
duplicate child
parent/child consistency
```

---

## 7.2 `remove_child()`

### Flow

```text
validate state
        ↓
verify exact parent identity
        ↓
verify exact child identity
        ↓
PlannerState.remove_child_task()
        ↓
return
```

No replanning is performed.

---

# 8. PlanningApplicationService

File:

```text
src/daypilot/application/planning_service.py
```

Exposes the explicit planning boundary:

```text
replan()
apply_replanning_result()
```

This service is different from the CRUD/change services because it exposes the planner's **preview and commit operations directly**.

---

## 8.1 `replan()`

### Purpose

Calculate a new plan without mutating PlannerState.

### Flow

```text
state + PlanningChange
        ↓
validate planning request
        ↓
domain replan()
        ↓
ReplanningResult
```

After this operation:

```text
current_plan unchanged
task state unchanged
dependency graph unchanged
observations unchanged
calendar events unchanged
constraints unchanged
```

The caller can inspect:

```text
new_plan
preserved_blocks
invalidated_blocks
rescheduled_blocks
unresolved_work
removed_tasks
```

before deciding to commit.

---

## 8.2 `apply_replanning_result()`

### Purpose

Explicitly commit a previously calculated planning proposal.

### Flow

```text
ReplanningResult
        ↓
validate state/result
        ↓
domain atomic commit
        ↓
return result
```

The application service does not duplicate the commit invariants.

The domain remains responsible for checking:

```text
task ownership
plan validity
block validity
dependency chronology
removed tasks
scheduling consistency
hierarchy integrity
```

---

# 9. DayPilotApplicationService

File:

```text
src/daypilot/application/application_service.py
```

The facade is the single entry point intended for external callers.

It does not contain business logic.

```text
External caller
      ↓
DayPilotApplicationService
      ↓
specific application service
      ↓
domain
```

The facade uses constructor injection so that its underlying services can be replaced with test doubles.

---

## 9.1 Task facade methods

```text
create_task()
change_task()
remove_task()
```

Each method simply forwards the request to:

```text
TaskApplicationService
```

---

## 9.2 Goal facade methods

```text
create_goal()
change_goal()
remove_goal()
```

Delegates to:

```text
GoalApplicationService
```

---

## 9.3 Dependency facade methods

```text
add_dependency()
remove_dependency()
```

Delegates to:

```text
DependencyApplicationService
```

---

## 9.4 Calendar facade methods

```text
add_calendar_event()
update_calendar_event()
remove_calendar_event()
```

Delegates to:

```text
CalendarApplicationService
```

The facade uses explicit calendar-specific names even though the underlying service methods are:

```text
add_event()
update_event()
remove_event()
```

---

## 9.5 Constraint facade methods

```text
add_constraint()
update_constraint()
remove_constraint()
```

Delegates to:

```text
ConstraintApplicationService
```

---

## 9.6 Observation facade

```text
record_observation()
```

Delegates to:

```text
ObservationApplicationService
```

---

## 9.7 Hierarchy facade

```text
add_child()
remove_child()
```

Delegates to:

```text
TaskHierarchyApplicationService
```

---

## 9.8 Planning facade

```text
replan()
apply_replanning_result()
```

Delegates to:

```text
PlanningApplicationService
```

This preserves the distinction between:

```text
replan()
    = preview/calculation

apply_replanning_result()
    = explicit commit
```

---

# 10. Application Request Models

Current request objects provide a boundary between external inputs and domain entities.

```text
TaskCreateRequest
TaskUpdateRequest

GoalUpdateRequest

CalendarEventUpdateRequest

ConstraintUpdateRequest

ObservationRequest
```

The request objects exist so callers do not need to construct domain objects for every modification request.

The application service converts request data into domain operations.

---

# 11. Application-Level Identity Model

Application services consistently use identity semantics.

Example:

```python
owned_task = Task(id="A", title="...")
lookalike = Task(id="A", title="...")
```

Even though:

```text
owned_task.id == lookalike.id
```

they are not interchangeable.

The application layer therefore verifies ownership using the actual object:

```text
existing is requested_object
```

This applies to:

```text
Task
Goal
CalendarEvent
Constraint
```

and dependency/hierarchy operations.

### Constraint identity and persistence

`Constraint` currently has no domain ID. The persistent application facade
therefore locates an existing constraint by value equality when handling
update and removal requests. This is a temporary limitation: an equal-valued
but distinct `Constraint` can match the stored constraint, even though the
application layer otherwise uses object identity for aggregate ownership.

Do not treat value equality as the intended identity contract. A future domain
and persistence design decision should give `Constraint` a stable logical ID
and resolve reconstructed constraints by that ID. That identity change is
deferred from the persistence application integration.

---

# 12. Application-Level Failure Model

State-changing application use cases fall into two patterns.

## Pattern A — Mutation + replanning

Used for:

```text
task update
task creation
dependency add/remove
calendar add/update/remove
constraint add/update/remove
observation recording
```

General form:

```text
mutate domain state
      ↓
calculate replanning
      ↓
commit
```

If the mutation occurred before the proposal/commit completed, the application service restores the mutation.

Examples:

```text
Task        → restore old field values
Dependency  → inverse edge operation
Calendar    → restore/remove event
Constraint  → restore/remove constraint
Observation → remove observation + restore task state
```

## Pattern B — Staged domain commit

Used for scheduled task removal:

```text
TASK_REMOVED
    ↓
replan()
    ↓
result.removed_tasks
    ↓
atomic domain commit
```

The application service does not manually remove the task.

---

# 13. Which Application Operations Trigger Replanning?

| Application operation | Replans? | Reason |
|---|---:|---|
| `create_task()` | ✅ | New schedulable work |
| `change_task()` | ✅ when planning-relevant | Task scheduling may change |
| `remove_task()` | ✅ for staged removal | Existing plan may change |
| `create_goal()` | ❌ | Goal metadata only |
| `change_goal()` | ❌ | Current domain does not model Goal scheduling impact |
| `remove_goal()` | ❌ | Goal lifecycle only |
| `add_dependency()` | ✅ | Chronology can change |
| `remove_dependency()` | ✅ | Dependency constraints may relax |
| `add_event()` | ✅ | Availability can change |
| `update_event()` | ✅ | Availability can change |
| `remove_event()` | ✅ | Time can become available |
| `add_constraint()` | ✅ | Availability/preferences can change |
| `update_constraint()` | ✅ | Availability/preferences can change |
| `remove_constraint()` | ✅ | Availability can change |
| `record_observation()` | ✅ | Remaining work/execution state can change |
| `add_child()` | ❌ | Hierarchy change only |
| `remove_child()` | ❌ | Hierarchy change only |
| `replan()` | proposal only | Explicit planning calculation |
| `apply_replanning_result()` | commit only | Explicit atomic commit |

---

# 14. Complete Application Workflow

A typical planning-affecting operation follows:

```text
External request
       │
       ▼
Application Service
       │
       ├── validate request
       ├── verify ownership
       ├── mutate PlannerState
       │
       ▼
PlanningChange
       │
       ▼
Domain replan()
       │
       ▼
ReplanningResult
       │
       ▼
Domain atomic commit
       │
       ▼
Application result
```

For example, changing a task duration:

```text
TaskUpdateRequest
      ↓
TaskApplicationService.change_task()
      ↓
update task duration
      ↓
PlanningChange(TASK_UPDATED)
      ↓
replan()
      ↓
old block invalidated
      ↓
new duration scheduled
      ↓
apply_replanning_result()
      ↓
new plan committed
```

---

# 15. Preview → Commit Workflow

The explicit planning API allows:

```text
1. User/request asks for a new plan.
2. Application calls replan().
3. Caller inspects ReplanningResult.
4. State is still unchanged.
5. Caller accepts the proposal.
6. Application calls apply_replanning_result().
7. Domain atomically commits it.
```

This gives DayPilot a future foundation for:

```text
schedule preview
schedule confirmation
manual approval
agent-generated proposals
```

without coupling those concepts to the domain layer.

---

# 16. Application Layer Responsibility Matrix

| Responsibility | Application Layer | Domain Layer |
|---|---:|---:|
| Request-shape validation | ✅ | |
| Exact object ownership | ✅ | ✅ |
| Create request objects | ✅ | |
| Call PlannerState operations | ✅ | |
| Construct PlanningChange | ✅ | |
| Decide planning impact | | ✅ |
| Calculate affected tasks | | ✅ |
| Calculate remaining work | | ✅ |
| Schedule work | | ✅ |
| Validate dependency graph | | ✅ |
| Validate hierarchy | | ✅ |
| Validate Plan | | ✅ |
| Atomic plan commit | | ✅ |
| Roll back application mutation after later failure | ✅ | |
| HTTP / Telegram / UI concerns | ❌ | ❌ |

---

# 17. Application Layer Design Principles

```text
1. One application method = one use case.

2. Application services orchestrate; they do not calculate domain rules.

3. PlannerState is the aggregate boundary for state changes.

4. Identity is preserved across the application boundary.

5. Planning changes are explicit.

6. Replanning is separated from committing.

7. Mutations performed before a later failure are restored.

8. Domain validation is not duplicated in application services.

9. The facade delegates rather than implementing business behavior.

10. External interfaces should call the application layer rather than the domain directly.
```

---

# 18. Testing Strategy

Application tests focus on use-case behavior rather than duplicating every domain invariant.

They verify:

```text
request validation
identity handling
state mutation orchestration
planning-change construction
replanning invocation
atomic commit
rollback
result propagation
cross-service workflows
facade delegation
```

The domain tests continue to act as the source of truth for:

```text
planning rules
dependency rules
hierarchy rules
observation rules
schedule rules
plan invariants
```

Current complete-suite baseline:

```text
248 passed
0 diagnostics
```

---

# 19. Repository Structure

```text
daypilot/
├── src/
│   └── daypilot/
│       ├── domain/
│       │   ├── goal.py
│       │   ├── task.py
│       │   ├── dependency_graph.py
│       │   ├── times.py
│       │   ├── schedule.py
│       │   ├── observation.py
│       │   ├── planner.py
│       │   └── replan.py
│       │
│       └── application/
│           ├── task_service.py
│           ├── goal_service.py
│           ├── dependency_service.py
│           ├── calendar_service.py
│           ├── constraint_service.py
│           ├── observation_service.py
│           ├── hierarchy_service.py
│           ├── planning_service.py
│           └── application_service.py
│
├── tests/
│   ├── domain/
│   └── application/
│
├── domain.md
└── README.md
```

---

# 20. Roadmap

## Phase 1 — Domain

Completed.

```text
Task hierarchy
Dependency graph
Time windows
Calendar events
Constraints
Scheduler
Plan
Observations
Remaining-work recovery
PlannerState
Replanning
Atomic result application
```

Detailed reference:

→ [Domain Model](domain.md)

---

## Phase 2 — Application

Completed.

```text
Task lifecycle
Goal lifecycle
Dependency lifecycle
Calendar lifecycle
Constraint lifecycle
Observation lifecycle
Hierarchy lifecycle
Planning preview/commit
Unified application facade
Cross-service workflows
```

This README contains the detailed application-method reference.

---

## Phase 3 — Persistence

Next.

The persistence phase should introduce:

```text
repository interfaces
persistence models
domain ↔ persistence mapping
PlannerState reconstruction
transaction boundaries
database implementation
```

The database should not leak into the domain layer.

---

## Phase 4 — Infrastructure

Planned:

```text
calendar provider
notification delivery
scheduled jobs
external services
```

---

## Phase 5 — Interfaces

Planned:

```text
FastAPI
CLI
Telegram
iPhone Shortcut integration
widget-facing APIs
```

---

# 21. End-to-End System Direction

The eventual DayPilot workflow is:

```text
capture task
      ↓
application service
      ↓
domain state mutation
      ↓
planning change
      ↓
replan
      ↓
plan proposal
      ↓
commit
      ↓
execute task
      ↓
record observation
      ↓
calculate remaining work
      ↓
replan again
      ↓
adaptive schedule
```

The architectural objective is to keep the core planning engine:

```text
deterministic
testable
state-consistent
interface-independent
persistence-independent
```

while allowing multiple future interfaces and infrastructure implementations to use the same application boundary.
