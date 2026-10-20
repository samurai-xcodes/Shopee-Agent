from uuid import uuid4

import pytest
from sqlalchemy import create_engine
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from database_models import Base, TaskRecord


@pytest.fixture
def engine(tmp_path):
    database = create_engine(f"sqlite:///{tmp_path / 'tasks.db'}")
    Base.metadata.create_all(database)
    yield database
    database.dispose()


def test_committed_task_survives_engine_recreation(engine):
    task_id = uuid4()
    with Session(engine) as session:
        session.add(TaskRecord(owner_id='test-owner', task_id=task_id, prompt="制作商品海报"))
        session.commit()

    database_url = engine.url
    engine.dispose()
    reopened = create_engine(database_url)
    try:
        with Session(reopened) as session:
            task = session.get(TaskRecord, task_id)
            assert task is not None
            assert task.task_id == task_id
            assert task.prompt == "制作商品海报"
            assert task.status == "PENDING"
    finally:
        reopened.dispose()


def test_rollback_discards_flushed_task(engine):
    task_id = uuid4()
    with Session(engine) as session:
        session.add(TaskRecord(owner_id='test-owner', task_id=task_id, prompt="不应保存的任务"))
        session.flush()
        session.rollback()

    with Session(engine) as session:
        assert session.get(TaskRecord, task_id) is None


def test_duplicate_primary_key_preserves_original_task(engine):
    task_id = uuid4()
    with Session(engine) as session:
        session.add(TaskRecord(owner_id='test-owner', task_id=task_id, prompt="原任务"))
        session.commit()

    with Session(engine) as session:
        session.add(TaskRecord(owner_id='test-owner', task_id=task_id, prompt="重复 ID 的任务"))
        with pytest.raises(IntegrityError):
            session.commit()
        session.rollback()

    with Session(engine) as session:
        task = session.get(TaskRecord, task_id)
        assert task is not None
        assert task.prompt == "原任务"
