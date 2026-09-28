# DayPilot — Domain Model Starter

This is the first inside-out milestone for the DayPilot planning agent.

## Current scope

Pure Python only:

- Goal
- Task
- TaskStatus
- Priority
- Initial tests

## Intentionally not included yet

- PostgreSQL
- SQLAlchemy
- Pydantic
- FastAPI
- LLM integration
- Dependency graph
- Calendar integration
- Scheduler

## Your next implementation tasks

1. Implement `Task.add_child()`
2. Implement `Task.remove_child()`
3. Implement `Task.reparent()`
4. Implement `Goal.add_root_task()`
5. Implement `Goal.remove_root_task()`
6. Add validation/invariants
7. Add tests for cycles and parent/child consistency
