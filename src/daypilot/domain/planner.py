from dataclasses import dataclass
from datetime import datetime
from daypilot.domain.dependency_graph import DependencyGraph
from daypilot.domain.enums import SchedulingStatus, TaskStatus
from daypilot.domain.goal import Goal
from daypilot.domain.observation import (
    Observation,
    process_observation,
    validate_observation_history,
    validate_observation_transition,
)
from daypilot.domain.schedule import Plan
from daypilot.domain.task import Task
from daypilot.domain.times import CalendarEvent, Constraint

@dataclass(eq=False)
class PlannerState:
    goals : list[Goal]
    tasks : list[Task]
    dependency_graph : DependencyGraph
    calendar_events : list[CalendarEvent]
    constraints : list[Constraint]
    current_plan : Plan | None
    observations : list[Observation]

    def __post_init__(self) -> None:
        if self.goals is None:
            raise ValueError("Goals cannot be None.")
        if self.tasks is None:
            raise ValueError("Tasks cannot be None.")
        if self.dependency_graph is None:
            raise ValueError("Dependency graph cannot be None.")
        if self.calendar_events is None:
            raise ValueError("Calendar events cannot be None.")
        if self.constraints is None:
            raise ValueError("Constraints cannot be None.")
        if self.observations is None:
            raise ValueError("Observations cannot be None.")
        if any(task is None for task in self.tasks):
            raise ValueError("Tasks cannot contain None.")
        if any(goal is None for goal in self.goals):
            raise ValueError("Goals cannot contain None.")
        if any(observation is None for observation in self.observations):
            raise ValueError("Observations cannot contain None.")

        for observation in self.observations:
            if not self._contains_task(observation.task):
                raise ValueError("Observation task is not in the list of tasks.")

        self._validate_plan_scheduling_consistency(self.current_plan, self.tasks)

        task_ids = [task.id for task in self.tasks]
        if len(task_ids) != len(set(task_ids)):
            raise ValueError("Task IDs must be unique.")

        state_tasks = {id(task) for task in self.tasks}
        if len(self.dependency_graph.tasks) != len(self.tasks) or any(
            self.dependency_graph.tasks.get(task.id) is not task for task in self.tasks
        ):
            raise ValueError("Planner tasks and dependency graph must contain the same task objects.")
        if any(event is None for event in self.calendar_events):
            raise ValueError("Calendar events cannot contain None.")
        if any(constraint is None for constraint in self.constraints):
            raise ValueError("Constraints cannot contain None.")

        goal_root_ids: set[int] = set()
        goal_ids: set[str] = set()
        for goal in self.goals:
            if goal.root_tasks is None:
                raise ValueError("Goal root tasks cannot be None.")
            if goal.id in goal_ids:
                raise ValueError(f"A goal with ID {goal.id!r} is duplicated.")
            goal_ids.add(goal.id)
            goal_root_ids_for_goal: set[int] = set()
            for root_task in goal.root_tasks:
                if id(root_task) not in state_tasks:
                    raise ValueError("Goal root task is not the same object as a planner task.")
                if root_task.parent is not None:
                    raise ValueError("Goal root task must not have a parent.")
                if self.dependency_graph.tasks.get(root_task.id) is not root_task:
                    raise ValueError("Goal root task is not registered in the dependency graph.")
                root_id = id(root_task)
                if root_id in goal_root_ids_for_goal:
                    raise ValueError("A Goal cannot contain duplicate root tasks.")
                goal_root_ids_for_goal.add(root_id)
                if root_id in goal_root_ids:
                    raise ValueError("A task cannot be a root task of multiple Goals.")
                goal_root_ids.add(root_id)

        self.validate_task_tree()
        for task in self.tasks:
            task_observations = [obs for obs in self.observations if obs.task is task]
            if task_observations:
                validate_observation_history(task, task_observations)

    def _contains_task(self, task: Task) -> bool:
        return any(existing is task for existing in self.tasks)

    @staticmethod
    def _remove_identity(items: list, target) -> bool:
        for index, existing in enumerate(items):
            if existing is target:
                del items[index]
                return True
        return False


    def add_task(self, task: Task) -> None:
        if task is None:
            raise ValueError("Task cannot be None.")
        if any(existing is task for existing in self.tasks):
            raise ValueError("Task is already in the planner state.")
        if any(existing.id == task.id for existing in self.tasks):
            raise ValueError(f"A task with ID {task.id!r} is already in the planner state.")
        registered = self.dependency_graph.tasks.get(task.id)
        if registered is not None:
            raise ValueError(f"A task with ID {task.id!r} is already registered in the dependency graph.")

        self.dependency_graph.register_task(task)
        self.tasks.append(task)

    def remove_task(self, task: Task) -> None:
        """Remove an unscheduled task; scheduled removal uses replanning."""
        self.validate_task_removal(task, allow_scheduled=False)
        self.dependency_graph.unregister_task(task)
        self._remove_identity(self.tasks, task)

    def validate_task_removal(self, task: Task, *, allow_scheduled: bool = False) -> None:
        if task is None:
            raise ValueError("Task cannot be None.")
        if not self._contains_task(task):
            raise ValueError("Task is not in the planner state.")
        if task.parent is not None:
            raise ValueError("Task must not have a parent.")
        if task.children:
            raise ValueError("Task must not have children.")
        if self.dependency_graph.dependents.get(task.id):
            raise ValueError("Task must not have dependents in the dependency graph.")
        if self.dependency_graph.prerequisites.get(task.id):
            raise ValueError("Task must not have prerequisites in the dependency graph.")
        if any(root is task for goal in self.goals for root in goal.root_tasks):
            raise ValueError("Task must not be a root task of any goal.")
        scheduled = self.current_plan is not None and any(
            block.task is task for block in self.current_plan.schedule_blocks
        )
        if scheduled and not allow_scheduled:
            raise ValueError("Scheduled tasks must be removed through replanning.")
        if any(observation for observation in self.observations if observation.task is task):
            raise ValueError("Task must not have any observations.")

    def add_goal(self, goal: Goal) -> None:
        if goal is None:
            raise ValueError("Goal cannot be None.")
        if any(existing is goal for existing in self.goals):
            raise ValueError("Goal is already in the planner state.")
        if any(existing.id == goal.id for existing in self.goals):
            raise ValueError(f"A goal with ID {goal.id!r} is already in the planner state.")

        for root_task in goal.root_tasks:
            if not any(existing is root_task for existing in self.tasks):
                raise ValueError("Goal root task is not in the planner state.")
            if root_task.parent is not None:
                raise ValueError("Goal root task must not have a parent.")
            registered = self.dependency_graph.tasks.get(root_task.id)
            if registered is not root_task:
                raise ValueError("Goal root task is not registered in the dependency graph.")
        #A root task can only belong to one goal, so we check that no other goal has the same root task.
        for existing_goal in self.goals:
            for root_task in existing_goal.root_tasks:
                if any(existing is root_task for existing in goal.root_tasks):
                    raise ValueError("A task cannot be a root task of multiple goals.")
        self.goals.append(goal)


    def remove_goal(self, goal: Goal)-> None:
        if goal is None:
            raise ValueError("Goal is None")
        if not any(existing is goal for existing in self.goals):
            raise ValueError('Goal is not present.')
        self._remove_identity(self.goals, goal)


    def add_observation(self, observation: Observation)-> None:
        if observation is None:
            raise ValueError("Observation is None")
        if not any(task is observation.task for task in self.tasks):            
            raise ValueError("Observation task is not in the planner state.")
        if any(existing is observation for existing in self.observations):
            raise ValueError("Observation is already in the planner state.")
        task_history = [obs for obs in self.observations if obs.task is observation.task]
        validate_observation_history(observation.task, task_history + [observation])
        validate_observation_transition(observation.task, observation)
        self.observations.append(observation)

    def record_observation(self, observation: Observation) -> None:
        """Record an observation and update the task's scheduling status."""
        self.add_observation(observation)
        process_observation(observation.task, observation)
        # Keep the old plan and task scheduling flags consistent until a
        # replanning result atomically replaces that plan.
        observation.task.scheduling_status = (
            SchedulingStatus.SCHEDULED
            if self.current_plan is not None
            and any(block.task is observation.task for block in self.current_plan.schedule_blocks)
            else SchedulingStatus.UNSCHEDULED
        )
        self.synchronize_task_states()


    def set_current_plan(self, plan: Plan | None) -> None:
        self.replace_current_plan(plan)


    def _validate_plan_scheduling_consistency(self, plan: Plan | None, tasks: list[Task]) -> None:
        if plan is None:
            for task in tasks:
                if task.scheduling_status != SchedulingStatus.UNSCHEDULED:
                    raise ValueError("Task with not active plan is scheduled.")
            return

        state_task_ids = {id(task) for task in tasks}
        scheduled_task_ids: set[int] = set()
        scheduled_ends: dict[Task, datetime] = {}
        for schedule in plan.schedule_blocks:
            task_id = id(schedule.task)
            if task_id not in state_task_ids:
                raise ValueError("Scheduled block task is not in the planner state.")
            if schedule.task.status in (TaskStatus.COMPLETED, TaskStatus.CANCELLED):
                raise ValueError("Completed or cancelled tasks cannot be scheduled.")
            scheduled_task_ids.add(task_id)
            scheduled_ends[schedule.task] = schedule.end

        for schedule in plan.schedule_blocks:
            for prerequisite in self.dependency_graph.get_prerequisites(schedule.task):
                if prerequisite.status is TaskStatus.COMPLETED:
                    continue
                prerequisite_end = scheduled_ends.get(prerequisite)
                if prerequisite_end is None or prerequisite_end > schedule.start:
                    raise ValueError("Plan violates task dependency chronology.")

        for task in tasks:
            is_scheduled = id(task) in scheduled_task_ids
            if is_scheduled and task.scheduling_status != SchedulingStatus.SCHEDULED:
                raise ValueError("Task scheduled in the plan has an inconsistent scheduling status.")
            if not is_scheduled and task.scheduling_status == SchedulingStatus.SCHEDULED:
                raise ValueError("Task marked as scheduled is not in the plan.")


    def replace_current_plan(self, new_plan: Plan | None) -> None:
        self.commit_replanned_plan(new_plan)

    def commit_replanned_plan(
        self,
        new_plan: Plan | None,
        removed_tasks: list[Task] | None = None,
    ) -> None:
        # Detect externally corrupted hierarchy before the commit changes any
        # scheduling status or removes tasks.
        self.validate_task_tree()
        if removed_tasks is None:
            removed_tasks = []
        if any(task is None for task in removed_tasks):
            raise ValueError("Removed tasks cannot contain None.")
        if len({id(task) for task in removed_tasks}) != len(removed_tasks):
            raise ValueError("Removed tasks cannot contain duplicates.")
        for task in removed_tasks:
            self.validate_task_removal(task, allow_scheduled=True)
            if self.dependency_graph.tasks.get(task.id) is not task:
                raise ValueError("Removed task is not registered in the dependency graph.")

        state_task_ids = {id(task) for task in self.tasks}
        removed_ids = {id(task) for task in removed_tasks}
        new_task_ids: set[int] = set()
        scheduled_ends: dict[Task, datetime] = {}
        if new_plan is not None:
            if new_plan.schedule_blocks is None:
                raise ValueError("Plan schedule blocks cannot be None.")
            if any(block is None for block in new_plan.schedule_blocks):
                raise ValueError("Plan schedule blocks cannot contain None.")
            if any(id(block.task) in removed_ids for block in new_plan.schedule_blocks):
                raise ValueError("Removed tasks cannot appear in the replacement plan.")
            horizon_end = new_plan.date + new_plan.planning_horizon
            for block in new_plan.schedule_blocks:
                task_id = id(block.task)
                if task_id not in state_task_ids:
                    raise ValueError("Scheduled block task is not in the planner state.")
                if not block.task.is_atomic:
                    raise ValueError("Scheduled block task must be atomic.")
                if block.task.status in (TaskStatus.COMPLETED, TaskStatus.CANCELLED):
                    raise ValueError("Completed or cancelled tasks cannot be scheduled.")
                if block.start >= block.end or block.start < new_plan.date or block.end > horizon_end:
                    raise ValueError("Scheduled block must lie within the plan horizon.")
                if task_id in new_task_ids:
                    raise ValueError("A task cannot have multiple schedule blocks.")
                new_task_ids.add(task_id)
                scheduled_ends[block.task] = block.end

            ordered_blocks = sorted(new_plan.schedule_blocks, key=lambda block: block.start)
            for previous, current in zip(ordered_blocks, ordered_blocks[1:]):
                if current.start < previous.end:
                    raise ValueError("Plan schedule blocks cannot overlap.")
            for block in new_plan.schedule_blocks:
                for prerequisite in self.dependency_graph.get_prerequisites(block.task):
                    if prerequisite.status == TaskStatus.COMPLETED:
                        continue
                    prerequisite_end = scheduled_ends.get(prerequisite)
                    if prerequisite_end is None or prerequisite_end > block.start:
                        raise ValueError("Plan violates task dependency chronology.")

        # All validation finishes before any planner state is changed.
        for task in removed_tasks:
            self.dependency_graph.unregister_task(task)
            self._remove_identity(self.tasks, task)

        for task in self.tasks:
            task_id = id(task)
            task.scheduling_status = (
                SchedulingStatus.SCHEDULED
                if task_id in new_task_ids
                else SchedulingStatus.UNSCHEDULED
            )

        self.current_plan = new_plan
        self.synchronize_task_states()


    # Unscheduling methods
    def unschedule_task(self, task: Task) -> None:
        if task is None:
            raise ValueError("Task is None")
        if not self._contains_task(task):
            raise ValueError("Task is not in the planner state.")
        if self.current_plan is None:
            raise ValueError("There is no current plan to unschedule from.")
        for block in self.current_plan.schedule_blocks:
            if block.task is task:
                self.current_plan.schedule_blocks.remove(block)
                task.scheduling_status = SchedulingStatus.UNSCHEDULED
                self.synchronize_task_states()
                return
        raise ValueError("Task is not scheduled in the current plan.")


    def unschedule_all_tasks(self) -> None:
        if self.current_plan is None:
            raise ValueError("There is no current plan to unschedule from.")
        for block in self.current_plan.schedule_blocks:
            block.task.scheduling_status = SchedulingStatus.UNSCHEDULED
        self.current_plan.schedule_blocks.clear()
        self.synchronize_task_states()


    # Calendar event methods
    def add_calendar_event(self, event: CalendarEvent) -> None:
        if event is None:
            raise ValueError("Calendar event is None")
        if any(existing is event for existing in self.calendar_events):
            raise ValueError("Calendar event is already in the planner state.")
        self.calendar_events.append(event)

    def remove_calendar_event(self, event: CalendarEvent) -> None:
        if event is None:
            raise ValueError("Calendar event is None")
        if not any(existing is event for existing in self.calendar_events):
            raise ValueError("Calendar event is not in the planner state.")
        self._remove_identity(self.calendar_events, event)


    # Constraint methods
    def add_constraint(self, constraint: Constraint) -> None:
        if constraint is None:
            raise ValueError("Constraint is None")
        if any(existing is constraint for existing in self.constraints):
            raise ValueError("Constraint is already in the planner state.")
        self.constraints.append(constraint)

    def remove_constraint(self, constraint: Constraint) -> None:
        if constraint is None:
            raise ValueError("Constraint is None")
        if not any(existing is constraint for existing in self.constraints):
            raise ValueError("Constraint is not in the planner state.")
        self._remove_identity(self.constraints, constraint)

    # Dependency methods
    def add_dependency(self, dependent: Task, prerequisite: Task) -> None:
        """Add a dependency between two tasks."""
        if dependent is None or prerequisite is None:
            raise ValueError("Dependent and prerequisite tasks cannot be None.")
        if not self._contains_task(dependent) or not self._contains_task(prerequisite):
            raise ValueError("Both tasks must be registered in the planner state.")
        self.dependency_graph.add_dependency(dependent, prerequisite)


    def remove_dependency(self, dependent: Task, prerequisite: Task) -> None:
        """ Remove a dependency between two tasks"""
        if dependent is None or prerequisite is None:
            raise ValueError("Dependent and prerequisite tasks cannot be None.")
        if not self._contains_task(dependent) or not self._contains_task(prerequisite):
            raise ValueError("Both tasks must be registered in the planner state.")

        self.dependency_graph.remove_dependency(dependent, prerequisite)


    # Task methods
    def add_child_task(self, parent: Task, child: Task) -> None:
        """Add child task for existing task."""
        if parent is None or child is None:
            raise ValueError("Parent and child tasks cannot be None.")
        if not self._contains_task(parent) or not self._contains_task(child):
            raise ValueError("Both tasks must be registered in the planner state.")
        if child.parent is not None:
            raise ValueError("Child task already has a parent.")
        if parent is child:
            raise ValueError("A task cannot be a child of itself.")
        if any(existing is child for existing in parent.children):
            raise ValueError("Child task is already a child of the parent task.")
        curr = parent
        while curr is not None:
            if curr is child:
                raise ValueError("Adding this child would create a cycle.")
            curr = curr.parent
        parent.children.append(child)
        child.parent = parent
        self.synchronize_task_states()

    def remove_child_task(self, parent: Task, child: Task) -> None:
        """Remove child task from existing task."""
        if parent is None or child is None:
            raise ValueError("Parent and child tasks cannot be None.")
        if not self._contains_task(parent) or not self._contains_task(child):
            raise ValueError("Both tasks must be registered in the planner state.")
        if child.parent is not parent:
            raise ValueError("Child task is not a child of the specified parent task.")
        self._remove_identity(parent.children, child)
        child.parent = None
        self.synchronize_task_states()

    def derive_task_status(self, task: Task) -> TaskStatus:
        if task is None:
            raise ValueError("Task cannot be None.")
        if not self._contains_task(task):
            raise ValueError("Task is not in the planner state.")
        if task.is_atomic:
            return task.status

        child_statuses = [
            self.derive_task_status(child)
            for child in task.children
        ]
        
        if all(status is TaskStatus.NOT_STARTED for status in child_statuses):
            return TaskStatus.NOT_STARTED
        
        if any(status is TaskStatus.BLOCKED for status in child_statuses):
            return TaskStatus.BLOCKED
        
        if any(status is TaskStatus.IN_PROGRESS for status in child_statuses):
            return TaskStatus.IN_PROGRESS
        
        if any(status is TaskStatus.CANCELLED for status in child_statuses):
            return TaskStatus.IN_PROGRESS
        
        if all(status is TaskStatus.COMPLETED for status in child_statuses):
            return TaskStatus.COMPLETED
        
        return TaskStatus.IN_PROGRESS

    def derive_task_scheduling_status(self, task: Task) -> SchedulingStatus:
        if task is None:
            raise ValueError("Task cannot be None.")
        if not self._contains_task(task):
            raise ValueError("Task is not in the planner state.")
        if task.is_atomic:
            return task.scheduling_status

        child_states = [
            (
                self.derive_task_status(child),
                self.derive_task_scheduling_status(child),
            )
            for child in task.children
        ]

        relevant_children = [
            (task_status, scheduling_status)
            for task_status, scheduling_status in child_states
            if task_status in (
                TaskStatus.NOT_STARTED,
                TaskStatus.IN_PROGRESS,
            )
        ]
        
        if not relevant_children:
            return SchedulingStatus.UNSCHEDULED

        if all(scheduling_status == SchedulingStatus.SCHEDULED for _, scheduling_status in relevant_children):
            return SchedulingStatus.SCHEDULED

        return SchedulingStatus.UNSCHEDULED


    def synchronize_composite_task_status(self, task: Task) -> None:
        """Synchronize a composite task and descendants from the leaves upward."""
        if task is None:
            raise ValueError("Task cannot be None.")
        if not self._contains_task(task):
            raise ValueError("Task is not in the planner state.")
        if task.is_atomic:
            return

        for child in task.children:
            self.synchronize_composite_task_status(child)

        task.status = self.derive_task_status(task)
        task.scheduling_status = self.derive_task_scheduling_status(task)


    def synchronize_task_states(self) -> None:
        """Synchronize each task tree, starting from its root."""
        for task in self.tasks:
            if task.parent is None:
                self.synchronize_composite_task_status(task)


    def validate_task_tree(self) -> None:
        if any(task is None for task in self.tasks):
            raise ValueError("Tasks cannot contain None.")

        task_ids = {id(task) for task in self.tasks}
        for task in self.tasks:
            child_ids = [id(child) for child in task.children]
            if len(child_ids) != len(set(child_ids)):
                raise ValueError("A task cannot contain duplicate children.")
            if task.parent is not None:
                if id(task.parent) not in task_ids:
                    raise ValueError("Task parent is not in the planner state.")
                if not any(child is task for child in task.parent.children):
                    raise ValueError("Task is missing from its parent's children.")

            for child in task.children:
                if id(child) not in task_ids:
                    raise ValueError("Task child is not in the planner state.")
                if child.parent is not task:
                    raise ValueError("Task child does not point back to its parent.")

        # Check every component, including cycles that have no root.
        visiting: set[int] = set()
        visited: set[int] = set()

        def visit(task: Task) -> None:
            task_id = id(task)
            if task_id in visiting:
                raise ValueError("Task hierarchy contains a cycle.")
            if task_id in visited:
                return
            visiting.add(task_id)
            for child in task.children:
                visit(child)
            visiting.remove(task_id)
            visited.add(task_id)

        for task in self.tasks:
            visit(task)
