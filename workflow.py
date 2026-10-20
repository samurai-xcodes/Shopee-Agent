from contextlib import contextmanager
from pathlib import Path
import time
from typing import TypedDict

from langgraph.graph import END, START, StateGraph
from langgraph.types import Command, interrupt
from sqlalchemy import select

from database_models import TaskRecord
from schemas import Brief, Document
from providers import safe_call
from service import audit
from storage import AssetStore


class State(TypedDict, total=False):
    prompt: str
    brief: dict
    candidates: list[dict]
    approval: dict


@contextmanager
def checkpointer(settings):
    if settings.database_url.startswith('postgresql'):
        from langgraph.checkpoint.postgres import PostgresSaver
        url = settings.database_url.replace('postgresql+psycopg://', 'postgresql://', 1)
        with PostgresSaver.from_conn_string(url) as saver:
            yield saver
    else:
        from langgraph.checkpoint.sqlite import SqliteSaver
        Path(settings.checkpoint_path).parent.mkdir(parents=True, exist_ok=True)
        with SqliteSaver.from_conn_string(settings.checkpoint_path) as saver:
            yield saver


def execute(task, settings, provider, factory):
    store = AssetStore(settings.storage_dir)
    deadline = time.monotonic() + settings.lease_seconds - 5

    def node_event(kind, **details):
        if time.monotonic() >= deadline:
            raise TimeoutError('Task execution budget exhausted')
        with factory.begin() as session:
            active = session.scalar(select(TaskRecord.task_id).where(
                TaskRecord.task_id == task.task_id, TaskRecord.status == 'RUNNING',
                TaskRecord.lease_token == task.lease_token, TaskRecord.lease_until > time.time()))
            if active is None:
                raise TimeoutError('Worker lease is no longer valid')
            audit(session, task.task_id, kind, trace_id=task.trace_id, **details)

    def parse(state):
        node_event('workflow.parse.started')
        started = time.monotonic()
        brief = safe_call(provider.parse, state['prompt'])
        node_event('workflow.parse.completed', duration_ms=round((time.monotonic() - started) * 1000),
                   simulated=provider.simulated, model=settings.text_model if not provider.simulated else 'mock',
                   usage=getattr(provider, 'last_usage', None))
        return {'brief': brief.model_dump()}

    def generate_node(index):
        def generate(state):
            node_event('tool.image.started', candidate=index + 1)
            started = time.monotonic()
            brief = Brief.model_validate(state['brief'])
            name = store.put(safe_call(provider.image, brief, index))
            document = Document(title=brief.title, price=brief.price, style=brief.style,
                                image_ref=name, simulated=provider.simulated)
            node_event('tool.image.completed', candidate=index + 1,
                       duration_ms=round((time.monotonic() - started) * 1000),
                       simulated=provider.simulated, model=settings.image_model if not provider.simulated else 'mock',
                       usage=getattr(provider, 'last_usage', None))
            return {'candidates': [*state.get('candidates', []), document.model_dump()]}
        return generate

    def approval(state):
        choice = interrupt({'action': 'select_and_approve', 'candidate_count': len(state['candidates'])})
        return {'approval': choice}

    builder = StateGraph(State)
    builder.add_node('parse', parse)
    for index in range(3):
        builder.add_node(f'image_{index}', generate_node(index))
    builder.add_node('approval', approval)
    builder.add_edge(START, 'parse')
    builder.add_edge('parse', 'image_0')
    builder.add_edge('image_0', 'image_1')
    builder.add_edge('image_1', 'image_2')
    builder.add_edge('image_2', 'approval')
    builder.add_edge('approval', END)
    with checkpointer(settings) as saver:
        graph = builder.compile(checkpointer=saver)
        config = {'configurable': {'thread_id': str(task.task_id)}}
        snapshot = graph.get_state(config)
        if snapshot.values and not snapshot.next:
            return snapshot.values
        if task.approved_version:
            argument = Command(resume={'version_id': str(task.approved_version)})
        else:
            argument = None if snapshot.values else {'prompt': task.prompt, 'candidates': []}
        return graph.invoke(argument, config)
