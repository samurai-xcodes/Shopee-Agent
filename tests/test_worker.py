from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
import time
from uuid import UUID

from sqlalchemy import select, update

from database_models import TaskRecord
from providers import MockProvider
from service import claim, finish
from worker import run_once


def submit(client):
    response = client.post('/tasks', json={'prompt': '运动鞋，轻便舒适，价格 99'})
    assert response.status_code == 201
    return response.json()['task_id']


def test_end_to_end_versions_approval_and_export(client, factory, settings):
    task_id = submit(client)
    path = f'/tasks/{task_id}'
    assert run_once(settings, factory)
    task = client.get(path).json()
    assert task['status'] == 'WAITING_APPROVAL'
    versions = client.get(path + '/versions').json()
    assert len(versions) == 3
    assert all(version['document']['simulated'] for version in versions)
    original = versions[0]
    preview = client.get(path + f"/versions/{original['version_id']}/preview")
    assert preview.status_code == 200 and preview.content.startswith(b'\x89PNG')
    edited = client.patch(path + f"/versions/{original['version_id']}", json={'price': '79'}).json()
    assert edited['document']['price'] == '79'
    assert edited['document']['image_ref'] == original['document']['image_ref']
    assert edited['document']['title'] == original['document']['title']
    restored = client.post(path + f"/versions/{original['version_id']}/restore").json()
    assert restored['document'] == original['document']
    payload = {'version_id': edited['version_id']}
    assert client.post(path + '/approve', json=payload).status_code == 200
    assert client.post(path + '/approve', json=payload).status_code == 200
    assert run_once(settings, factory)
    assert client.get(path).json()['status'] == 'SUCCESS'
    assert client.post(path + '/approve', json=payload).status_code == 200
    assert client.get(path + '/export?format=json').json() == edited['document']
    assert client.get(path + '/export?format=svg').content.startswith(b'<svg')
    assert client.get(path + '/export?format=png').content.startswith(b'\x89PNG')
    assert client.patch(path + f"/versions/{original['version_id']}", json={'price': '9'}).status_code == 409
    events = client.get(path + '/events').json()
    assert sum(item['kind'] == 'tool.image.completed' for item in events) == 3
    assert any(item['kind'] == 'task.success' for item in events)


def test_checkpoint_resume_does_not_regenerate(client, factory, settings):
    task_id = submit(client)
    assert run_once(settings, factory)
    version = client.get(f'/tasks/{task_id}/versions').json()[0]
    client.post(f'/tasks/{task_id}/approve', json={'version_id': version['version_id']})

    class MustNotCallProvider:
        simulated = True
        def parse(self, *_):
            raise AssertionError('Should resume checkpoint instead of calling provider')
        image = parse

    assert run_once(settings, factory, MustNotCallProvider())
    assert client.get(f'/tasks/{task_id}').json()['status'] == 'SUCCESS'


def test_worker_failure_is_explainable(client, factory, settings):
    task_id = submit(client)

    class Broken(MockProvider):
        def parse(self, _):
            raise ValueError('sensitive-provider-body-must-not-leak')

    assert run_once(settings, factory, Broken())
    data = client.get(f'/tasks/{task_id}').json()
    assert data['status'] == 'FAILED'
    assert data['error'] == 'ValueError'
    assert 'sensitive' not in str(data)


def test_expired_claim_retries_and_fences_old_worker(client, factory, settings):
    task_id = UUID(submit(client))
    old = claim(factory, settings)
    with factory.begin() as session:
        session.execute(update(TaskRecord).where(TaskRecord.task_id == task_id).values(lease_until=time.time() - 1))
    assert claim(factory, settings) is None  # recovery applies backoff
    assert not finish(factory, old, {})
    with factory.begin() as session:
        session.execute(update(TaskRecord).where(TaskRecord.task_id == task_id).values(available_at=0))
    current = claim(factory, settings)
    assert current.attempts == 2
    assert current.lease_token != old.lease_token
    assert not finish(factory, old, {})


def test_exhausted_claim_is_failed(client, factory, settings):
    task_id = UUID(submit(client))
    limited = replace(settings, max_attempts=1)
    assert claim(factory, limited)
    with factory.begin() as session:
        session.execute(update(TaskRecord).where(TaskRecord.task_id == task_id).values(lease_until=0))
    assert claim(factory, limited) is None
    assert client.get(f'/tasks/{task_id}').json()['status'] == 'FAILED'


def test_unknown_openai_outcome_not_automatically_retried(client, factory, settings):
    task_id = UUID(submit(client))
    with factory.begin() as session:
        session.execute(update(TaskRecord).where(TaskRecord.task_id == task_id).values(provider='openai'))
    assert claim(factory, settings)
    with factory.begin() as session:
        session.execute(update(TaskRecord).where(TaskRecord.task_id == task_id).values(lease_until=0))
    assert claim(factory, settings) is None
    data = client.get(f'/tasks/{task_id}').json()
    assert data['status'] == 'FAILED'
    assert 'unknown' in data['error']


def test_concurrent_claim_has_one_winner(client, factory, settings):
    submit(client)
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _: claim(factory, settings), range(2)))
    assert sum(result is not None for result in results) == 1


def test_concurrent_idempotency_has_one_task(app, factory, settings):
    from service import create_task
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _: create_task(factory, settings, 'alice', 'same', 'same'), range(2)))
    assert results[0][0].task_id == results[1][0].task_id
    assert sum(created for _, created in results) == 1


def test_edit_and_asset_isolation(client, factory, settings):
    task_id = submit(client)
    run_once(settings, factory)
    version = client.get(f'/tasks/{task_id}/versions').json()[0]
    path = f"/tasks/{task_id}/versions/{version['version_id']}"
    assert client.get(path + '/preview', headers={'X-Dev-User': 'bob'}).status_code == 404
    assert client.patch(path, json={'price': '1'}, headers={'X-Dev-User': 'bob'}).status_code == 404
    assert client.patch(path, json={'image_ref': 'replace.png'}).status_code == 422
    assert client.patch(path, json={'price': None}).status_code == 422
    assert client.patch(path, json={}).status_code == 422


def test_bounded_retry(client, factory, settings):
    task_id = UUID(submit(client))

    class TemporarilyBroken(MockProvider):
        def parse(self, _):
            raise ConnectionError('temporary')

    for _ in range(settings.max_attempts):
        with factory.begin() as session:
            session.execute(update(TaskRecord).where(TaskRecord.task_id == task_id).values(available_at=0))
        run_once(settings, factory, TemporarilyBroken())
    task = client.get(f'/tasks/{task_id}').json()
    assert task['status'] == 'FAILED'
    assert task['attempts'] == settings.max_attempts


def test_manual_retry_preserves_task_identity(client, factory, settings):
    task_id = submit(client)
    with factory.begin() as session:
        session.execute(update(TaskRecord).where(TaskRecord.task_id == UUID(task_id)).values(status='FAILED', error='temporary'))
    response = client.post(f'/tasks/{task_id}/retry', json={})
    assert response.status_code == 200
    assert response.json()['task_id'] == task_id
    assert response.json()['status'] == 'PENDING'
    assert run_once(settings, factory)
    assert client.get(f'/tasks/{task_id}').json()['status'] == 'WAITING_APPROVAL'


def test_openai_retry_requires_explicit_acknowledgement(client, factory):
    task_id = submit(client)
    with factory.begin() as session:
        session.execute(update(TaskRecord).where(TaskRecord.task_id == UUID(task_id)).values(status='FAILED', provider='openai'))
    assert client.post(f'/tasks/{task_id}/retry', json={}).status_code == 409
    assert client.post(f'/tasks/{task_id}/retry', json={'acknowledge_possible_duplicate_charge': True}).status_code == 200


def test_resume_after_second_candidate_failure(client, factory, settings):
    task_id = UUID(submit(client))

    class FailsOnce(MockProvider):
        calls = []
        def image(self, brief, index):
            self.calls.append(index)
            if index == 1 and self.calls.count(1) == 1:
                raise ConnectionError('transient provider error body')
            return super().image(brief, index)

    provider = FailsOnce()
    run_once(settings, factory, provider)
    assert client.get(f'/tasks/{task_id}').json()['status'] == 'PENDING'
    with factory.begin() as session:
        session.execute(update(TaskRecord).where(TaskRecord.task_id == task_id).values(available_at=0))
    run_once(settings, factory, provider)
    assert provider.calls == [0, 1, 1, 2]
    assert client.get(f'/tasks/{task_id}').json()['status'] == 'WAITING_APPROVAL'
    assert len(client.get(f'/tasks/{task_id}/versions').json()) == 3


def test_concurrent_queue_admission_is_bounded(app, factory, settings):
    from fastapi import HTTPException
    from service import create_task
    limited = replace(settings, queue_limit=1)
    def submit_owner(owner):
        try:
            create_task(factory, limited, owner, 'hello', None)
            return 201
        except HTTPException as error:
            return error.status_code
    with ThreadPoolExecutor(max_workers=2) as pool:
        statuses = list(pool.map(submit_owner, ['alice', 'bob']))
    assert sorted(statuses) == [201, 503]
