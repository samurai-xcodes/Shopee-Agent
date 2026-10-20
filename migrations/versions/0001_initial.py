"""Initial durable tasks, versions, audit and request metrics."""
from alembic import op
import sqlalchemy as sa

revision = '0001'
down_revision = None
branch_labels = None
depends_on = None


def upgrade():
    op.create_table('tasks',
        sa.Column('task_id', sa.Uuid(), primary_key=True),
        sa.Column('owner_id', sa.String(100), nullable=False),
        sa.Column('prompt', sa.Text(), nullable=False),
        sa.Column('status', sa.String(30), nullable=False),
        sa.Column('created_at', sa.Float(), nullable=False),
        sa.Column('updated_at', sa.Float(), nullable=False),
        sa.Column('idempotency_key', sa.String(128)),
        sa.Column('request_hash', sa.String(64), nullable=False),
        sa.Column('attempts', sa.Integer(), nullable=False),
        sa.Column('available_at', sa.Float(), nullable=False),
        sa.Column('lease_until', sa.Float()),
        sa.Column('lease_token', sa.String(36)),
        sa.Column('error', sa.Text()),
        sa.Column('result_ref', sa.String(200)),
        sa.Column('approved_version', sa.Uuid()),
        sa.Column('result', sa.JSON()),
        sa.Column('trace_id', sa.String(36), nullable=False),
        sa.Column('provider', sa.String(20), nullable=False),
        sa.UniqueConstraint('owner_id', 'idempotency_key', name='uq_task_idempotency'),
        sa.CheckConstraint("status IN ('PENDING','RUNNING','WAITING_APPROVAL','SUCCESS','FAILED')", name='ck_task_status'),
        sa.CheckConstraint('length(trim(prompt)) > 0', name='ck_prompt_nonempty'))
    op.create_index('ix_tasks_queue', 'tasks', ['status', 'available_at'])
    op.create_index('ix_tasks_owner_created', 'tasks', ['owner_id', 'created_at'])
    op.create_table('versions',
        sa.Column('version_id', sa.Uuid(), primary_key=True),
        sa.Column('task_id', sa.Uuid(), sa.ForeignKey('tasks.task_id'), nullable=False),
        sa.Column('number', sa.Integer(), nullable=False),
        sa.Column('parent_id', sa.Uuid()),
        sa.Column('document', sa.JSON(), nullable=False),
        sa.Column('created_at', sa.Float(), nullable=False),
        sa.UniqueConstraint('task_id', 'number', name='uq_version_number'))
    op.create_index('ix_versions_task_id', 'versions', ['task_id'])
    op.create_table('events',
        sa.Column('event_id', sa.Uuid(), primary_key=True),
        sa.Column('task_id', sa.Uuid(), sa.ForeignKey('tasks.task_id'), nullable=False),
        sa.Column('kind', sa.String(50), nullable=False),
        sa.Column('details', sa.JSON(), nullable=False),
        sa.Column('created_at', sa.Float(), nullable=False))
    op.create_index('ix_events_task_id', 'events', ['task_id'])
    op.create_table('owners', sa.Column('owner_id', sa.String(100), primary_key=True))
    op.create_table('request_metrics',
        sa.Column('request_id', sa.Uuid(), primary_key=True),
        sa.Column('owner_id', sa.String(100), nullable=False),
        sa.Column('route', sa.String(200), nullable=False),
        sa.Column('status_code', sa.Integer(), nullable=False),
        sa.Column('latency_ms', sa.Float(), nullable=False),
        sa.Column('created_at', sa.Float(), nullable=False))
    op.create_index('ix_request_metrics_owner_id', 'request_metrics', ['owner_id'])


def downgrade():
    for name in ('request_metrics', 'owners', 'events', 'versions', 'tasks'):
        op.drop_table(name)
