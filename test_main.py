from uuid import UUID

import pytest
from fastapi.testclient import TestClient

from main import app, tasks


@pytest.fixture(autouse=True)
def isolate_tasks():
    tasks.clear()
    yield
    tasks.clear()


def test_health():
    with TestClient(app) as client:
        response = client.get("/health")

    assert response.status_code == 200
    assert response.headers["content-type"] == "application/json"
    assert response.json() == {"status": "ok"}


def test_create_task():
    with TestClient(app) as client:
        response = client.post("/tasks", json={"prompt": "  制作商品海报  "})

    assert response.status_code == 201
    data = response.json()
    task_id = UUID(data["task_id"])
    assert task_id.version == 4
    assert data == {
        "task_id": str(task_id),
        "prompt": "制作商品海报",
        "status": "PENDING",
    }
    assert tasks[task_id].model_dump(mode="json") == data
    assert len(tasks) == 1


@pytest.mark.parametrize(
    "payload",
    [
        {},
        {"prompt": ""},
        {"prompt": "   "},
        {"prompt": "\t\n"},
        {"prompt": None},
        {"prompt": 123},
        {"prompt": []},
        {"prompt": {}},
    ],
)
def test_reject_invalid_prompt(payload):
    with TestClient(app) as client:
        response = client.post("/tasks", json=payload)

    assert response.status_code == 422
    assert response.json()["detail"][0]["loc"] == ["body", "prompt"]
    assert tasks == {}


def test_repeated_submissions_create_separate_tasks():
    with TestClient(app) as client:
        first = client.post("/tasks", json={"prompt": "制作商品海报"})
        second = client.post("/tasks", json={"prompt": "制作商品海报"})

    assert first.status_code == second.status_code == 201
    assert first.json()["task_id"] != second.json()["task_id"]
    assert len(tasks) == 2


def test_get_created_task():
    with TestClient(app) as client:
        created = client.post("/tasks", json={"prompt": "制作商品海报"})
        assert created.status_code == 201
        data = created.json()
        other = client.post("/tasks", json={"prompt": "制作另一张海报"})
        assert other.status_code == 201

        for _ in range(2):
            response = client.get(f"/tasks/{data['task_id']}")
            assert response.status_code == 200
            assert response.json() == data

    assert len(tasks) == 2


def test_get_unknown_task():
    with TestClient(app) as client:
        response = client.get("/tasks/00000000-0000-4000-8000-000000000000")

    assert response.status_code == 404
    assert response.json() == {"detail": "Task not found"}
    assert tasks == {}


def test_get_task_with_invalid_uuid():
    with TestClient(app) as client:
        response = client.get("/tasks/not-a-uuid")

    assert response.status_code == 422
    assert response.json()["detail"][0]["loc"] == ["path", "task_id"]
    assert tasks == {}
