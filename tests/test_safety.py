from dataclasses import replace
from io import BytesIO
import json
from unittest.mock import Mock
from uuid import UUID

import pytest
from PIL import Image
from sqlalchemy import text

from database import migrate
from database_models import TaskRecord
from providers import MockProvider, OpenAIProvider
from schemas import Brief
from storage import AssetStore, render_svg
from worker import run_once


def test_migrations_are_repeatable(app):
    migrate(app.state.engine)
    migrate(app.state.engine)
    with app.state.engine.connect() as connection:
        assert connection.scalar(text('SELECT version_num FROM alembic_version')) == '0001'


def test_asset_store_rejects_traversal_and_invalid_images(tmp_path):
    store = AssetStore(tmp_path)
    with pytest.raises(ValueError):
        store.read('../secret.png')
    with pytest.raises(Exception):
        store.put(b'not an image')


def test_svg_escapes_user_text(tmp_path):
    store = AssetStore(tmp_path)
    brief = MockProvider().parse('demo')
    name = store.put(MockProvider().image(brief, 0))
    document = {'title': '<script>alert(1)</script>', 'price': '<&>', 'image_ref': name, 'simulated': True}
    svg = render_svg(document, store)
    assert b'<script>' not in svg
    assert b'&lt;script&gt;' in svg
    assert b'SIMULATED DEMO' in svg


def test_openai_adapter_uses_structured_output_and_no_hidden_retries(settings, monkeypatch):
    import base64
    import openai
    client = Mock()
    constructor = Mock(return_value=client)
    monkeypatch.setattr(openai, 'OpenAI', constructor)
    provider = OpenAIProvider(replace(settings, provider='openai'))
    constructor.assert_called_once_with(timeout=settings.provider_timeout, max_retries=0)
    brief = Brief(product='shoe', selling_points=['light'], style='clean', title='shoe', price='99')
    client.responses.parse.return_value = Mock(output_parsed=brief, usage=None)
    assert provider.parse('shoe 99') == brief
    assert client.responses.parse.call_args.kwargs['text_format'] is Brief
    assert client.responses.parse.call_args.kwargs['store'] is False
    image = MockProvider().image(brief, 0)
    client.images.generate.return_value = Mock(data=[Mock(b64_json=base64.b64encode(image).decode())], usage=None)
    assert provider.image(brief, 0) == image
    assert client.images.generate.call_args.kwargs['n'] == 1


def test_no_silent_mock_fallback_for_openai_task(client, factory, settings, monkeypatch):
    from sqlalchemy import update
    monkeypatch.delenv('OPENAI_API_KEY', raising=False)
    task = client.post('/tasks', json={'prompt': 'real request'}).json()
    task_id = UUID(task['task_id'])
    with factory.begin() as session:
        session.execute(update(TaskRecord).where(TaskRecord.task_id == task_id).values(provider='openai'))
    run_once(settings, factory)
    result = client.get(f'/tasks/{task_id}').json()
    assert result['status'] == 'FAILED'
    assert client.get(f'/tasks/{task_id}/versions').json() == []


def test_web_studio_is_served(client):
    response = client.get('/')
    assert response.status_code == 200
    assert 'text/html' in response.headers['content-type']
    assert 'Creative Studio' in response.text
    assert 'localStorage' not in response.text
