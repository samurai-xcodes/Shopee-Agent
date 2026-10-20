from dataclasses import replace
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select

from database_models import TaskRecord
from main import create_app


def test_health(client):
    response = client.get('/health')
    assert response.status_code == 200
    assert response.json() == {'status': 'ok'}
    assert response.headers['content-type'] == 'application/json'
    assert UUID(response.headers['X-Trace-ID'])
    assert client.get('/ready').status_code == 200


def test_create_task(client, factory):
    response = client.post('/tasks', json={'prompt': '  制作商品海报  '})
    assert response.status_code == 201
    data = response.json()
    task_id = UUID(data['task_id'])
    assert task_id.version == 4
    assert data['prompt'] == '制作商品海报'
    assert data['status'] == 'PENDING'
    assert response.headers['Location'] == f'/tasks/{task_id}'
    with factory() as session:
        assert session.get(TaskRecord, task_id).owner_id == 'alice'


@pytest.mark.parametrize('payload', [{}, {'prompt': ''}, {'prompt': '   '}, {'prompt': '\t\n'},
                                     {'prompt': None}, {'prompt': 123}, {'prompt': []}, {'prompt': {}},
                                     {'prompt': 'x' * 4001}, {'prompt': 'hello', 'owner_id': 'bob'}])
def test_reject_invalid_prompt(client, factory, payload):
    assert client.post('/tasks', json=payload).status_code == 422
    with factory() as session:
        assert session.scalar(select(func.count()).select_from(TaskRecord)) == 0


def test_repeated_submissions_create_separate_tasks(client):
    first = client.post('/tasks', json={'prompt': '海报'})
    second = client.post('/tasks', json={'prompt': '海报'})
    assert first.status_code == second.status_code == 201
    assert first.json()['task_id'] != second.json()['task_id']


def test_get_created_task(client):
    first = client.post('/tasks', json={'prompt': '第一张海报'}).json()
    client.post('/tasks', json={'prompt': '第二张海报'})
    for _ in range(2):
        response = client.get(f"/tasks/{first['task_id']}")
        assert response.status_code == 200
        assert response.json() == first


def test_get_unknown_task(client):
    response = client.get(f'/tasks/{uuid4()}')
    assert response.status_code == 404
    assert response.json() == {'detail': 'Task not found'}


def test_invalid_uuid(client):
    response = client.get('/tasks/not-a-uuid')
    assert response.status_code == 422
    assert response.json()['detail'][0]['loc'] == ['path', 'task_id']


def test_auth_and_isolation(client):
    task = client.post('/tasks', json={'prompt': 'alice task'}).json()
    path = f"/tasks/{task['task_id']}"
    for suffix in ('', '/versions', '/events', '/export'):
        assert client.get(path + suffix, headers={'X-Dev-User': 'bob'}).status_code == 404
    assert client.get('/tasks', headers={'X-Dev-User': 'bob'}).json() == []
    assert client.get('/tasks', headers={'X-Dev-User': ''}).status_code == 401


def test_persistence_across_app_instances(client, settings):
    task = client.post('/tasks', json={'prompt': 'persistent'}).json()
    application = create_app(settings)
    with TestClient(application, headers={'X-Dev-User': 'alice'}) as second:
        assert second.get(f"/tasks/{task['task_id']}").json() == task


def test_idempotency(client):
    headers = {'Idempotency-Key': 'same-request'}
    first = client.post('/tasks', json={'prompt': 'hello'}, headers=headers)
    repeat = client.post('/tasks', json={'prompt': 'hello'}, headers=headers)
    assert first.status_code == 201
    assert repeat.status_code == 200
    assert first.json() == repeat.json()
    assert client.post('/tasks', json={'prompt': 'different'}, headers=headers).status_code == 409
    assert client.post('/tasks', json={'prompt': 'hello'}, headers={**headers, 'X-Dev-User': 'bob'}).status_code == 201


def test_export_requires_confirmation(client):
    task = client.post('/tasks', json={'prompt': 'hello'}).json()
    assert client.get(f"/tasks/{task['task_id']}/export").status_code == 409


def test_token_mode_ignores_development_identity(app, settings):
    configured = replace(settings, auth_mode='token', api_tokens={'alice': 'test-only-' + 'a' * 32})
    application = create_app(configured)
    with TestClient(application) as client:
        assert client.get('/tasks', headers={'X-Dev-User': 'alice'}).status_code == 401
        assert client.get('/tasks', headers={'Authorization': 'Bearer incorrect'}).status_code == 401
        assert client.get('/tasks', headers={'Authorization': 'Bearer test-only-' + 'a' * 32}).status_code == 200


def test_rate_limit_and_queue_capacity(app, settings):
    configured = replace(settings, requests_per_minute=1, queue_limit=1)
    with TestClient(create_app(configured), headers={'X-Dev-User': 'alice'}) as client:
        assert client.post('/tasks', json={'prompt': 'one'}).status_code == 201
        assert client.post('/tasks', json={'prompt': 'two'}).status_code == 429
        assert client.post('/tasks', json={'prompt': 'three'}, headers={'X-Dev-User': 'bob'}).status_code == 503


def test_metrics_are_owner_scoped(client):
    client.post('/tasks', json={'prompt': 'hello'})
    metrics = client.get('/metrics').json()
    assert metrics['tasks_by_status']['PENDING'] == 1
    assert metrics['request_p95_ms'] is not None
    assert metrics['provider_cost_usd'] is None
    assert client.get('/metrics', headers={'X-Dev-User': 'bob'}).json()['tasks_by_status'] == {}
