from unittest.mock import Mock

from fastapi.testclient import TestClient

from daypilot.api.app import create_app
from daypilot.api.dependencies import get_persistent_application
from daypilot.domain.task import Task


def test_task_create_and_retrieve(api_client):
    created = api_client.post(
        "/tasks",
        json={
            "id": "task-1",
            "title": "Write tests",
            "estimated_duration_microseconds": 1_800_000_000,
        },
    )

    assert created.status_code == 201
    assert created.json()["id"] == "task-1"
    assert created.json()["estimated_duration_microseconds"] == 1_800_000_000

    retrieved = api_client.get("/tasks/task-1")
    assert retrieved.status_code == 200
    assert retrieved.json()["title"] == "Write tests"
    assert retrieved.json()["status"] == "not_started"


def test_task_update(api_client):
    api_client.post("/tasks", json={"id": "task-1", "title": "Initial"})

    updated = api_client.patch("/tasks/task-1", json={"title": "Updated"})

    assert updated.status_code == 200
    assert updated.json()["title"] == "Updated"


def test_task_delete(api_client):
    api_client.post("/tasks", json={"id": "task-1", "title": "Remove"})

    deleted = api_client.delete("/tasks/task-1")

    assert deleted.status_code == 204
    assert api_client.get("/tasks/task-1").status_code == 404


def test_goal_create_and_retrieve(api_client):
    api_client.post("/tasks", json={"id": "root-task", "title": "Root"})
    created = api_client.post(
        "/goals",
        json={
            "id": "goal-1",
            "title": "Ship API",
            "description": "First release",
            "root_task_ids": ["root-task"],
        },
    )

    assert created.status_code == 201
    assert created.json()["id"] == "goal-1"
    assert created.json()["root_task_ids"] == ["root-task"]

    retrieved = api_client.get("/goals/goal-1")
    assert retrieved.status_code == 200
    assert retrieved.json()["title"] == "Ship API"


def test_goal_update_and_delete(api_client):
    api_client.post("/goals", json={"id": "goal-1", "title": "Initial"})

    updated = api_client.patch("/goals/goal-1", json={"title": "Updated"})
    assert updated.status_code == 200
    assert updated.json()["title"] == "Updated"

    deleted = api_client.delete("/goals/goal-1")
    assert deleted.status_code == 204
    assert api_client.get("/goals/goal-1").status_code == 404


def test_validation_failure_returns_422(api_client):
    response = api_client.post(
        "/tasks",
        json={"id": "bad-duration", "title": "Invalid", "estimated_duration_microseconds": 0},
    )

    assert response.status_code == 422


def test_domain_validation_failure_returns_422(api_client):
    api_client.post("/tasks", json={"id": "task-1", "title": "Existing"})

    response = api_client.post("/tasks", json={"id": "task-1", "title": "Duplicate"})

    assert response.status_code == 422
    assert "already" in response.json()["detail"].lower()


def test_missing_entity_returns_404(api_client):
    response = api_client.get("/tasks/missing")

    assert response.status_code == 404
    assert "missing" in response.json()["detail"]


def test_persistent_application_is_injectable_through_fastapi_dependency():
    application = Mock()
    application.get_task.return_value = Task("task-1", "Injected")
    app = create_app(state_id="state-1")
    app.dependency_overrides[get_persistent_application] = lambda: application

    with TestClient(app) as client:
        response = client.get("/tasks/task-1")

    assert response.status_code == 200
    assert response.json()["title"] == "Injected"
    application.get_task.assert_called_once_with("state-1", "task-1")
