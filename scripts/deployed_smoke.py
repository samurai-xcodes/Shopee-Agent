"""Verify a running local mock deployment over HTTP; refuses real-provider mode."""
import json
import os
from pathlib import Path
import time
from urllib.request import Request, urlopen
from uuid import uuid4


def main():
    base = os.getenv('DEPLOYED_URL', 'http://127.0.0.1:8002')
    owner = 'deployment-smoke-' + uuid4().hex[:12]

    def request(path, payload=None, method=None):
        req = Request(base + path, data=json.dumps(payload).encode() if payload is not None else None,
                      method=method, headers={'Content-Type': 'application/json', 'X-Dev-User': owner})
        with urlopen(req, timeout=5) as response:
            content = response.read()
            return response.status, json.loads(content) if 'application/json' in response.headers.get('Content-Type', '') else content

    assert request('/ready')[1]['provider'] == 'mock', 'This smoke command only supports mock mode'
    assert request('/')[0] == 200
    code, task = request('/tasks', {'prompt': '运动鞋，价格 99，蓝色简洁风格'})
    assert code == 201
    path = '/tasks/' + task['task_id']

    def wait(status):
        for _ in range(100):
            current = request(path)[1]
            if current['status'] == status:
                return
            if current['status'] == 'FAILED':
                raise RuntimeError('Task failed: ' + str(current['error']))
            time.sleep(0.1)
        raise RuntimeError('Timed out waiting for ' + status)

    wait('WAITING_APPROVAL')
    versions = request(path + '/versions')[1]
    assert len(versions) == 3
    original = versions[0]
    code, edited = request(path + '/versions/' + original['version_id'], {'price': '79'}, 'PATCH')
    assert code == 201 and edited['document']['image_ref'] == original['document']['image_ref']
    request(path + '/approve', {'version_id': edited['version_id']})
    wait('SUCCESS')
    data = request(path + '/export?format=png')[1]
    assert data.startswith(b'\x89PNG')
    Path('data').mkdir(exist_ok=True)
    Path('data/container-export.png').write_bytes(data)
    Path('data/deployed-smoke.json').write_text(json.dumps({'task_id': task['task_id'], 'owner': owner}))
    print('PASS: deployed Studio + API + Worker + PostgreSQL + price edit + approval + PNG export')


if __name__ == '__main__':
    main()
