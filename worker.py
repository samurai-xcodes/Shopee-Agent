import argparse
import json
import logging
import signal
import time
from dataclasses import replace
from sqlalchemy.exc import SQLAlchemyError

from database import make_engine, sessions
from providers import ProviderCallError, make_provider
from service import claim, fail, finish
from settings import Settings
from workflow import execute

logger = logging.getLogger(__name__)


def run_once(settings, factory, provider=None):
    task = claim(factory, settings)
    if task is None:
        return False
    settings = replace(settings, provider=task.provider)
    started = time.monotonic()
    managed_provider = provider is None
    try:
        provider = provider or make_provider(settings)
        result = execute(task, settings, provider, factory)
        accepted = finish(factory, task, result)
        logger.info(json.dumps({'event': 'worker.finished', 'task_id': str(task.task_id),
                               'trace_id': task.trace_id, 'accepted': accepted,
                               'duration_ms': round((time.monotonic() - started) * 1000)}))
    except Exception as error:
        # Never persist provider response bodies, prompts, credentials or raw exception strings.
        code = error.safe_code if isinstance(error, ProviderCallError) else type(error).__name__
        retryable = error.retryable if isinstance(error, ProviderCallError) else isinstance(error, (TimeoutError, ConnectionError))
        fail(factory, settings, task, code, retryable=retryable)
        logger.error(json.dumps({'event': 'worker.failed', 'task_id': str(task.task_id),
                                'trace_id': task.trace_id, 'error_type': code}))
    finally:
        if managed_provider and provider is not None and hasattr(provider, 'close'):
            try:
                provider.close()
            except Exception:
                logger.warning('{"event":"provider.cleanup_failed"}')
    return True


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--once', action='store_true')
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format='%(message)s')
    settings = Settings.from_env()
    engine = make_engine(settings.database_url)
    factory = sessions(engine)
    stopping = False

    def stop(*_):
        nonlocal stopping
        stopping = True

    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
    try:
        while not stopping:
            try:
                worked = run_once(settings, factory)
            except SQLAlchemyError:
                logger.error('{"event":"worker.database_unavailable"}')
                if args.once:
                    raise
                time.sleep(1)
                continue
            if args.once:
                break
            if not worked:
                time.sleep(0.5)
    finally:
        engine.dispose()


if __name__ == '__main__':
    main()
