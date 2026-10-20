import os
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url

from database import make_engine, migrate, sessions
from main import create_app
from settings import Settings


@pytest.fixture(params=['sqlite'] + (['postgres'] if os.getenv('TEST_DATABASE_URL') else []))
def settings(request, tmp_path):
    admin = None
    schema = None
    if request.param == 'postgres':
        admin = create_engine(os.environ['TEST_DATABASE_URL'])
        schema = 'test_' + uuid4().hex
        with admin.begin() as connection:
            connection.execute(text(f'CREATE SCHEMA "{schema}"'))
        url = make_url(os.environ['TEST_DATABASE_URL']).update_query_dict({'options': f'-csearch_path={schema}'})
        database_url = url.render_as_string(hide_password=False)
    else:
        database_url = f'sqlite:///{tmp_path / "app.db"}'
    yield Settings(database_url=database_url, storage_dir=tmp_path / 'assets',
                   checkpoint_path=str(tmp_path / 'checkpoints.db'))
    if admin:
        with admin.begin() as connection:
            connection.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))
        admin.dispose()


@pytest.fixture
def app(settings):
    application = create_app(settings)
    migrate(application.state.engine)
    yield application
    application.state.engine.dispose()


@pytest.fixture
def client(app):
    with TestClient(app, headers={'X-Dev-User': 'alice'}) as client:
        yield client


@pytest.fixture
def factory(app):
    return app.state.sessions
