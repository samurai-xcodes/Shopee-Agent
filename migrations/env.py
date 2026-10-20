from alembic import context
from database_models import Base

connection = context.config.attributes.get('connection')
if connection is None:
    from database import make_engine
    from settings import Settings
    engine = make_engine(Settings.from_env().database_url)
    with engine.connect() as connection:
        context.configure(connection=connection, target_metadata=Base.metadata)
        with context.begin_transaction():
            context.run_migrations()
    engine.dispose()
else:
    context.configure(connection=connection, target_metadata=Base.metadata)
    with context.begin_transaction():
        context.run_migrations()
