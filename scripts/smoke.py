"""Exercise real API/Worker processes and an API restart; always uses mock generation."""
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import tempfile
import time
from contextlib import contextmanager
from uuid import uuid4
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


@contextmanager
def smoke_database(temporary):
    url = os.getenv('SMOKE_DATABASE_URL')
    if not url:
        yield f'sqlite:///{temporary}/tasks.db'
        return
    from sqlalchemy import create_engine, text
    from sqlalchemy.engine import make_url
    admin = create_engine(url)
    schema = 'smoke_' + uuid4().hex
    try:
        with admin.begin() as connection:
            connection.execute(text(f'CREATE SCHEMA "{schema}"'))
        isolated = make_url(url).update_query_dict({'options': f'-csearch_path={schema}'})
        yield isolated.render_as_string(hide_password=False)
    finally:
        with admin.begin() as connection:
            connection.execute(text(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE'))
        admin.dispose()


def main():
    root = Path(__file__).resolve().parents[1]
    with tempfile.TemporaryDirectory(prefix='shopee-smoke-') as temporary, smoke_database(temporary) as database_url:
        env = {**os.environ, 'DATABASE_URL': database_url,
               'STORAGE_DIR': f'{temporary}/assets', 'CHECKPOINT_PATH': f'{temporary}/checkpoints.db',
               'AUTH_MODE': 'dev', 'PROVIDER': 'mock'}
        subprocess.run([sys.executable, '-m', 'database'], cwd=root, env=env, check=True, capture_output=True)
        listener = socket.socket()
        listener.bind(('127.0.0.1', 0))
        listener.listen(128)
        base = f'http://127.0.0.1:{listener.getsockname()[1]}'
        processes = []

        def request(path, payload=None):
            req = Request(base + path, data=json.dumps(payload).encode() if payload is not None else None,
                          headers={'Content-Type': 'application/json', 'X-Dev-User': 'smoke-user'})
            try:
                response = urlopen(req, timeout=2)
            except HTTPError as error:
                response = error
            with response:
                content = response.read()
                return response.status, json.loads(content) if 'application/json' in response.headers.get('Content-Type', '') else content

        def wait_for(path, predicate):
            deadline = time.monotonic() + 30
            while time.monotonic() < deadline:
                try:
                    response = request(path)
                    if predicate(response):
                        return response
                except (URLError, TimeoutError, ConnectionError):
                    pass
                time.sleep(0.1)
            raise RuntimeError(f'Timed out waiting for {path}')

        with tempfile.TemporaryFile(mode='w+') as logs:
            def start_api():
                process = subprocess.Popen([sys.executable, '-m', 'uvicorn', 'main:app', '--fd', str(listener.fileno())],
                                           cwd=root, env=env, pass_fds=(listener.fileno(),), stdout=logs, stderr=logs)
                processes.append(process)
                wait_for('/ready', lambda value: value[0] == 200)
                return process
            try:
                api = start_api()
                code, task = request('/tasks', {'prompt': 'Smoke test ecommerce poster'})
                assert code == 201
                path = '/tasks/' + task['task_id']
                api.terminate()
                api.wait(timeout=5)
                api = start_api()
                assert request(path)[0] == 200
                processes.append(subprocess.Popen([sys.executable, '-m', 'worker'], cwd=root, env=env, stdout=logs, stderr=logs))
                wait_for(path, lambda value: value[1]['status'] == 'WAITING_APPROVAL')
                version = request(path + '/versions')[1][0]
                assert request(path + '/approve', {'version_id': version['version_id']})[0] == 200
                wait_for(path, lambda value: value[1]['status'] == 'SUCCESS')
                assert request(path + '/export?format=png')[1].startswith(b'\x89PNG')
                print('PASS: real HTTP create -> API restart -> persisted query -> independent Worker -> approval -> PNG export')
            finally:
                for process in reversed(processes):
                    if process.poll() is None:
                        process.terminate()
                        try:
                            process.wait(timeout=10)
                        except subprocess.TimeoutExpired:
                            process.kill()
                            process.wait()
                listener.close()


if __name__ == '__main__':
    main()
