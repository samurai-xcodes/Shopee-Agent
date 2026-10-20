import hashlib
import time
from uuid import uuid4

from fastapi import HTTPException
from sqlalchemy import func, select, update

from database_models import EventRecord, OwnerRecord, TaskRecord, VersionRecord
from schemas import TaskView, VersionView


def audit(session, task_id, kind, **details):
    session.add(EventRecord(task_id=task_id, kind=kind, details=details))


def owned_task(session, task_id, owner, lock=False):
    query = select(TaskRecord).where(TaskRecord.task_id == task_id, TaskRecord.owner_id == owner)
    task = session.scalar(query.with_for_update() if lock else query)
    if task is None:
        raise HTTPException(404, 'Task not found')
    return task


def owned_version(session, task_id, version_id, owner):
    owned_task(session, task_id, owner)
    version = session.scalar(select(VersionRecord).where(
        VersionRecord.task_id == task_id, VersionRecord.version_id == version_id))
    if version is None:
        raise HTTPException(404, 'Version not found')
    return version


def create_task(factory, settings, owner, prompt, key):
    fingerprint = hashlib.sha256((settings.provider + '\0' + prompt).encode()).hexdigest()
    with factory.begin() as session:
        # A durable per-owner lock serializes admission, quota and idempotency decisions.
        if session.bind.dialect.name == 'postgresql':
            from sqlalchemy.dialects.postgresql import insert
        else:
            from sqlalchemy.dialects.sqlite import insert
        session.execute(insert(OwnerRecord).values(owner_id=owner).on_conflict_do_nothing())
        session.scalar(select(OwnerRecord).where(OwnerRecord.owner_id == owner).with_for_update())
        if key:
            existing = session.scalar(select(TaskRecord).where(
                TaskRecord.owner_id == owner, TaskRecord.idempotency_key == key))
            if existing:
                if existing.request_hash != fingerprint:
                    raise HTTPException(409, 'Idempotency key already used for a different request')
                return TaskView.model_validate(existing), False
        session.execute(insert(OwnerRecord).values(owner_id='__queue_admission__').on_conflict_do_nothing())
        session.scalar(select(OwnerRecord).where(OwnerRecord.owner_id == '__queue_admission__').with_for_update())
        now = time.time()
        for seconds, limit in ((60, settings.requests_per_minute), (86400, settings.tasks_per_day)):
            count = session.scalar(select(func.count()).select_from(TaskRecord).where(
                TaskRecord.owner_id == owner, TaskRecord.created_at >= now - seconds))
            if count >= limit:
                raise HTTPException(429, 'Task quota exceeded', headers={'Retry-After': str(seconds)})
        pending = session.scalar(select(func.count()).select_from(TaskRecord).where(
            TaskRecord.status.in_(['PENDING', 'RUNNING'])))
        if pending >= settings.queue_limit:
            raise HTTPException(503, 'Queue capacity reached', headers={'Retry-After': '10'})
        task = TaskRecord(task_id=uuid4(), owner_id=owner, prompt=prompt,
                          provider=settings.provider, idempotency_key=key, request_hash=fingerprint)
        session.add(task)
        session.flush()
        audit(session, task.task_id, 'task.created', provider=settings.provider)
        return TaskView.model_validate(task), True


def add_version(session, task, document, parent_id=None):
    number = (session.scalar(select(func.max(VersionRecord.number)).where(
        VersionRecord.task_id == task.task_id)) or 0) + 1
    version = VersionRecord(task_id=task.task_id, number=number,
                            parent_id=parent_id, document=document)
    session.add(version)
    session.flush()
    return version


def edit_version(factory, task_id, version_id, owner, changes):
    if not changes or any(value is None for value in changes.values()):
        raise HTTPException(422, 'Provide a non-null title or price')
    with factory.begin() as session:
        task = owned_task(session, task_id, owner, lock=True)
        if task.status != 'WAITING_APPROVAL':
            raise HTTPException(409, 'Edits require a task awaiting approval')
        old = owned_version(session, task_id, version_id, owner)
        document = {**old.document, **changes}
        version = add_version(session, task, document, old.version_id)
        audit(session, task_id, 'version.edited', version_id=str(version.version_id), fields=sorted(changes))
        return VersionView.model_validate(version)


def restore_version(factory, task_id, version_id, owner):
    with factory.begin() as session:
        task = owned_task(session, task_id, owner, lock=True)
        if task.status != 'WAITING_APPROVAL':
            raise HTTPException(409, 'Restore requires a task awaiting approval')
        source = owned_version(session, task_id, version_id, owner)
        version = add_version(session, task, dict(source.document), source.version_id)
        audit(session, task_id, 'version.restored', version_id=str(version.version_id))
        return VersionView.model_validate(version)


def approve(factory, task_id, version_id, owner):
    with factory.begin() as session:
        task = owned_task(session, task_id, owner, lock=True)
        owned_version(session, task_id, version_id, owner)
        if task.approved_version == version_id and task.status in {'PENDING', 'RUNNING', 'SUCCESS'}:
            return TaskView.model_validate(task)
        if task.status != 'WAITING_APPROVAL':
            raise HTTPException(409, 'Task is not awaiting approval')
        task.approved_version = version_id
        task.status = 'PENDING'
        task.available_at = time.time()
        task.attempts = 0
        task.updated_at = time.time()
        audit(session, task_id, 'task.approved', version_id=str(version_id))
        session.flush()
        return TaskView.model_validate(task)


def claim(factory, settings):
    now = time.time()
    with factory.begin() as session:
        expired = session.scalars(select(TaskRecord).where(
            TaskRecord.status == 'RUNNING', TaskRecord.lease_until < now
        ).with_for_update(skip_locked=True).limit(100)).all()
        for task in expired:
            uncertain = task.provider == 'openai' and task.approved_version is None
            status = 'FAILED' if task.attempts >= settings.max_attempts or uncertain else 'PENDING'
            recovered = session.execute(update(TaskRecord).where(
                TaskRecord.task_id == task.task_id, TaskRecord.status == 'RUNNING',
                TaskRecord.lease_token == task.lease_token, TaskRecord.lease_until < now
            ).values(status=status,
                     error='Worker lease expired; external outcome may be unknown' if uncertain else 'Worker lease expired',
                     available_at=now + min(60, 2 ** min(task.attempts, 6)), lease_token=None, lease_until=None,
                     updated_at=now).execution_options(synchronize_session=False)).rowcount
            if recovered:
                audit(session, task.task_id, 'task.recovered', status=status)
        session.flush()
        task = session.scalar(select(TaskRecord).where(
            TaskRecord.status == 'PENDING', TaskRecord.available_at <= now,
            TaskRecord.attempts < settings.max_attempts
        ).order_by(TaskRecord.created_at).with_for_update(skip_locked=True).limit(1))
        if task is None:
            return None
        token = str(uuid4())
        count = session.execute(update(TaskRecord).where(
            TaskRecord.task_id == task.task_id, TaskRecord.status == 'PENDING',
            TaskRecord.attempts == task.attempts
        ).values(status='RUNNING', attempts=task.attempts + 1,
                 lease_token=token, lease_until=now + settings.lease_seconds,
                 updated_at=now, error=None).execution_options(synchronize_session=False)).rowcount
        if count != 1:
            return None
        session.refresh(task)
        audit(session, task.task_id, 'task.running', attempt=task.attempts)
        return task


def finish(factory, task, result):
    with factory.begin() as session:
        current = session.scalar(select(TaskRecord).where(
            TaskRecord.task_id == task.task_id, TaskRecord.status == 'RUNNING',
            TaskRecord.lease_token == task.lease_token, TaskRecord.lease_until > time.time()
        ).with_for_update())
        if current is None:
            return False
        if current.approved_version:
            current.status = 'SUCCESS'
            current.result_ref = str(current.approved_version)
        else:
            count = session.scalar(select(func.count()).select_from(VersionRecord).where(
                VersionRecord.task_id == task.task_id))
            if not count:
                for document in result['candidates']:
                    add_version(session, current, document)
            current.status = 'WAITING_APPROVAL'
        current.result = {'brief': result['brief'], 'simulated': task.provider == 'mock'}
        current.updated_at = time.time()
        current.lease_until = None
        current.lease_token = None
        audit(session, task.task_id, 'task.' + current.status.lower())
        return True


def fail(factory, settings, task, error_code, retryable=False):
    with factory.begin() as session:
        current = session.scalar(select(TaskRecord).where(
            TaskRecord.task_id == task.task_id, TaskRecord.status == 'RUNNING',
            TaskRecord.lease_token == task.lease_token, TaskRecord.lease_until > time.time()
        ).with_for_update())
        if current is None:
            return False
        retry = retryable and current.attempts < settings.max_attempts and current.provider == 'mock'
        current.status = 'PENDING' if retry else 'FAILED'
        current.available_at = time.time() + min(60, 2 ** min(current.attempts, 6))
        current.error = error_code
        current.updated_at = time.time()
        current.lease_token = None
        current.lease_until = None
        audit(session, task.task_id, 'task.error', code=error_code, retry=retry)
        return True
