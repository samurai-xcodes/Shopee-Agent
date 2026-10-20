import json
import logging
import math
import time
from contextlib import asynccontextmanager
from typing import Annotated, Literal
from uuid import UUID, uuid4
from pathlib import Path

from fastapi import Depends, FastAPI, Header, HTTPException, Query, Request, Response
from fastapi.responses import FileResponse
from fastapi.responses import JSONResponse
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy import func, select, text

from auth import current_owner
from database import make_engine, sessions
from database_models import EventRecord, RequestRecord, TaskRecord, VersionRecord
from schemas import Approval, EditRequest, RetryRequest, TaskCreate, TaskView, VersionView
from service import approve, create_task, edit_version, owned_task, owned_version, restore_version
from settings import Settings
from storage import AssetStore, render_png, render_svg

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)
if not logger.handlers:
    logger.addHandler(logging.StreamHandler())
logger.propagate = False
Owner = Annotated[str, Depends(current_owner)]


def create_app(settings=None):
    settings = settings or Settings.from_env()
    engine = make_engine(settings.database_url)
    factory = sessions(engine)

    @asynccontextmanager
    async def lifespan(app):
        # Schema changes are an explicit deployment step, never a side effect of importing main.
        with engine.connect() as connection:
            connection.execute(select(TaskRecord.task_id).limit(0))
        yield
        engine.dispose()

    app = FastAPI(title='Shopee Creative Agent', version='0.2.0', lifespan=lifespan,
                  description='Development identity mode requires X-Dev-User and is not production authentication.'
                  if settings.auth_mode == 'dev' else 'Authenticate using a provisioned Bearer token.')
    app.state.settings = settings
    app.state.engine = engine
    app.state.sessions = factory

    @app.exception_handler(SQLAlchemyError)
    async def database_error(request, error):
        logger.error('{"event":"database.unavailable"}')
        return JSONResponse(status_code=503, content={'detail': 'Database temporarily unavailable'},
                            headers={'Retry-After': '5'})

    @app.get('/', include_in_schema=False)
    def studio():
        return FileResponse(Path(__file__).with_name('web') / 'index.html',
                            headers={'Cache-Control': 'no-store'})

    @app.middleware('http')
    async def request_trace(request, call_next):
        trace_id = str(uuid4())
        started = time.monotonic()
        response = await call_next(request)
        response.headers['X-Trace-ID'] = trace_id
        duration = (time.monotonic() - started) * 1000
        owner = getattr(request.state, 'owner_id', None)
        route = request.scope.get('route')
        route_name = route.path if route else 'unmatched'
        if owner:
            try:
                with factory.begin() as session:
                    session.add(RequestRecord(owner_id=owner, route=route_name,
                                              status_code=response.status_code, latency_ms=duration))
            except Exception:
                logger.warning('request_metrics_write_failed')
        logger.info(json.dumps({'event': 'http.request', 'trace_id': trace_id, 'route': route_name,
                                'status': response.status_code, 'duration_ms': round(duration, 2)}))
        return response

    @app.get('/health')
    def health():
        return {'status': 'ok'}

    @app.get('/ready')
    def ready():
        try:
            with engine.connect() as connection:
                connection.execute(select(TaskRecord.task_id).limit(0))
        except Exception:
            raise HTTPException(503, 'Database unavailable') from None
        return {'status': 'ready', 'provider': settings.provider, 'auth_mode': settings.auth_mode}

    @app.post('/tasks', status_code=201, response_model=TaskView)
    def submit(body: TaskCreate, owner: Owner, response: Response,
               idempotency_key: Annotated[str | None, Header(min_length=1, max_length=128)] = None):
        task, created = create_task(factory, settings, owner, body.prompt, idempotency_key)
        if not created:
            response.status_code = 200
        response.headers['Location'] = f'/tasks/{task.task_id}'
        return task

    @app.get('/tasks', response_model=list[TaskView])
    def list_tasks(owner: Owner, limit: int = Query(20, ge=1, le=100), offset: int = Query(0, ge=0)):
        with factory() as session:
            rows = session.scalars(select(TaskRecord).where(TaskRecord.owner_id == owner)
                                   .order_by(TaskRecord.created_at.desc()).offset(offset).limit(limit))
            return [TaskView.model_validate(row) for row in rows]

    @app.get('/tasks/{task_id}', response_model=TaskView)
    def get_task(task_id: UUID, owner: Owner):
        with factory() as session:
            return TaskView.model_validate(owned_task(session, task_id, owner))

    @app.get('/tasks/{task_id}/events')
    def events(task_id: UUID, owner: Owner, limit: int = Query(100, ge=1, le=500)):
        with factory() as session:
            owned_task(session, task_id, owner)
            rows = session.scalars(select(EventRecord).where(EventRecord.task_id == task_id)
                                   .order_by(EventRecord.created_at).limit(limit))
            return [{'kind': row.kind, 'details': row.details, 'created_at': row.created_at} for row in rows]

    @app.post('/tasks/{task_id}/retry', response_model=TaskView)
    def retry(task_id: UUID, body: RetryRequest, owner: Owner):
        from service import audit
        with factory.begin() as session:
            task = owned_task(session, task_id, owner, lock=True)
            if task.status != 'FAILED':
                raise HTTPException(409, 'Only failed tasks can be retried')
            if task.provider == 'openai' and not body.acknowledge_possible_duplicate_charge:
                raise HTTPException(409, 'Acknowledge possible duplicate provider charges before retrying')
            task.status, task.attempts, task.error = 'PENDING', 0, None
            task.available_at = task.updated_at = time.time()
            task.lease_token = task.lease_until = None
            audit(session, task_id, 'task.retry_requested', duplicate_charge_acknowledged=body.acknowledge_possible_duplicate_charge)
            session.flush()
            return TaskView.model_validate(task)

    @app.get('/tasks/{task_id}/versions', response_model=list[VersionView])
    def versions(task_id: UUID, owner: Owner, limit: int = Query(100, ge=1, le=500), offset: int = Query(0, ge=0)):
        with factory() as session:
            owned_task(session, task_id, owner)
            rows = session.scalars(select(VersionRecord).where(VersionRecord.task_id == task_id)
                                   .order_by(VersionRecord.number).offset(offset).limit(limit))
            return [VersionView.model_validate(row) for row in rows]

    @app.patch('/tasks/{task_id}/versions/{version_id}', status_code=201, response_model=VersionView)
    def edit(task_id: UUID, version_id: UUID, body: EditRequest, owner: Owner):
        return edit_version(factory, task_id, version_id, owner, body.model_dump(exclude_unset=True))

    @app.post('/tasks/{task_id}/versions/{version_id}/restore', status_code=201, response_model=VersionView)
    def restore(task_id: UUID, version_id: UUID, owner: Owner):
        return restore_version(factory, task_id, version_id, owner)

    @app.post('/tasks/{task_id}/approve', response_model=TaskView)
    def confirm(task_id: UUID, body: Approval, owner: Owner):
        return approve(factory, task_id, body.version_id, owner)

    @app.get('/tasks/{task_id}/versions/{version_id}/preview')
    def preview(task_id: UUID, version_id: UUID, owner: Owner):
        with factory() as session:
            version = owned_version(session, task_id, version_id, owner)
            payload = render_png(version.document, AssetStore(settings.storage_dir))
        return Response(payload, media_type='image/png', headers={'Cache-Control': 'private, no-store'})

    @app.get('/tasks/{task_id}/export')
    def export(task_id: UUID, owner: Owner, format: Literal['svg', 'png', 'json'] = 'svg'):
        with factory() as session:
            task = owned_task(session, task_id, owner)
            if task.status != 'SUCCESS' or not task.approved_version:
                raise HTTPException(409, 'Approve a version and wait for SUCCESS before exporting')
            version = owned_version(session, task_id, task.approved_version, owner)
            store = AssetStore(settings.storage_dir)
            if format == 'json':
                payload = json.dumps(version.document, ensure_ascii=False).encode()
                content_type = 'application/json'
            elif format == 'png':
                payload, content_type = render_png(version.document, store), 'image/png'
            else:
                payload, content_type = render_svg(version.document, store), 'image/svg+xml'
        return Response(payload, media_type=content_type,
                        headers={'Content-Disposition': f'attachment; filename="{task_id}.{format}"',
                                 'Cache-Control': 'private, no-store', 'X-Content-Type-Options': 'nosniff'})

    @app.get('/metrics')
    def metrics(owner: Owner):
        with factory() as session:
            latencies = sorted(session.scalars(select(RequestRecord.latency_ms).where(
                RequestRecord.owner_id == owner).order_by(RequestRecord.created_at.desc()).limit(1000)))
            counts = dict(session.execute(select(TaskRecord.status, func.count()).where(
                TaskRecord.owner_id == owner).group_by(TaskRecord.status)).all())
            calls = session.execute(select(EventRecord.kind, EventRecord.details).join(
                TaskRecord, TaskRecord.task_id == EventRecord.task_id).where(
                TaskRecord.owner_id == owner, EventRecord.kind.in_(['tool.image.completed', 'workflow.parse.completed'])))
            model_calls = list(calls)
            failed_requests = session.scalar(select(func.count()).select_from(RequestRecord).where(
                RequestRecord.owner_id == owner, RequestRecord.status_code >= 500))
        def percentile(value):
            return round(latencies[max(0, math.ceil(len(latencies) * value) - 1)], 2) if latencies else None
        return {'sample': 'last_1000_owner_requests', 'request_p50_ms': percentile(0.5),
                'request_p95_ms': percentile(0.95), 'tasks_by_status': counts,
                'server_error_requests_total': failed_requests, 'model_calls_completed': len(model_calls),
                'simulated_calls': sum(bool(details.get('simulated')) for _, details in model_calls),
                'provider_cost_usd': None, 'cost_note': 'No billing data available; not an estimate of provider charges'}

    return app


app = create_app()
