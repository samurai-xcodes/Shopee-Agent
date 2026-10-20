from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, event
from sqlalchemy.engine import make_url
from sqlalchemy.orm import sessionmaker


def make_engine(url):
    parsed = make_url(url)
    if parsed.get_backend_name() == 'sqlite' and parsed.database not in {None, '', ':memory:'}:
        Path(parsed.database).parent.mkdir(parents=True, exist_ok=True)
    engine = create_engine(url, pool_pre_ping=True,
                           connect_args={'check_same_thread': False, 'timeout': 30} if parsed.get_backend_name() == 'sqlite' else {})
    if engine.dialect.name == 'sqlite':
        @event.listens_for(engine, 'connect')
        def configure(connection, _):
            connection.execute('PRAGMA foreign_keys=ON')
            connection.execute('PRAGMA journal_mode=WAL')
    return engine


def migrate(engine):
    config = Config(str(Path(__file__).with_name('alembic.ini')))
    config.set_main_option('script_location', str(Path(__file__).with_name('migrations')))
    with engine.begin() as connection:
        config.attributes['connection'] = connection
        command.upgrade(config, 'head')
    if engine.dialect.name == 'postgresql':
        from langgraph.checkpoint.postgres import PostgresSaver
        url = engine.url.render_as_string(hide_password=False).replace('postgresql+psycopg://', 'postgresql://', 1)
        with PostgresSaver.from_conn_string(url) as saver:
            saver.setup()


def sessions(engine):
    return sessionmaker(engine, expire_on_commit=False)


if __name__ == '__main__':
    from settings import Settings
    engine = make_engine(Settings.from_env().database_url)
    try:
        migrate(engine)
        print('Database migrations applied')
    finally:
        engine.dispose()
