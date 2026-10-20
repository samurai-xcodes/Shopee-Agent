"""Local mock functional eval; this does not measure actual model or visual quality."""
from dataclasses import replace
import json
import math
from pathlib import Path
import tempfile
import time

from fastapi.testclient import TestClient

from database import migrate
from main import create_app
from settings import Settings
from worker import run_once


def main():
    cases = json.loads(Path(__file__).with_name('cases.json').read_text())
    rows = []
    with tempfile.TemporaryDirectory(prefix='shopee-eval-') as directory:
        settings = Settings(database_url=f'sqlite:///{directory}/eval.db',
                            storage_dir=Path(directory) / 'assets', checkpoint_path=f'{directory}/checkpoints.db',
                            requests_per_minute=1000, tasks_per_day=1000)
        app = create_app(settings)
        migrate(app.state.engine)
        with TestClient(app, headers={'X-Dev-User': 'eval-user'}) as client:
            for case in cases:
                started = time.perf_counter()
                passed = False
                try:
                    created = client.post('/tasks', json={'prompt': case['prompt']})
                    assert created.status_code == 201
                    path = '/tasks/' + created.json()['task_id']
                    run_once(settings, app.state.sessions)
                    assert client.get(path).json()['status'] == 'WAITING_APPROVAL'
                    versions = client.get(path + '/versions').json()
                    assert len(versions) == 3
                    original = versions[0]
                    edited = client.patch(path + '/versions/' + original['version_id'], json={'price': '79'}).json()
                    assert edited['document']['image_ref'] == original['document']['image_ref']
                    assert edited['document']['title'] == original['document']['title']
                    assert edited['document']['price'] == '79'
                    assert edited['document']['simulated'] is True
                    assert client.post(path + '/approve', json={'version_id': edited['version_id']}).status_code == 200
                    run_once(settings, app.state.sessions)
                    assert client.get(path).json()['status'] == 'SUCCESS'
                    assert client.get(path + '/export?format=png').content.startswith(b'\x89PNG')
                    events = client.get(path + '/events').json()
                    assert sum(event['kind'] == 'tool.image.completed' for event in events) == 3
                    passed = True
                except AssertionError:
                    pass
                rows.append({'id': case['id'], 'category': case['category'], 'passed': passed,
                             'latency_ms': round((time.perf_counter() - started) * 1000, 2)})
    latencies = sorted(row['latency_ms'] for row in rows)
    percentile = lambda p: latencies[max(0, math.ceil(len(latencies) * p) - 1)]
    summary = {'mode': 'mock_functional_only', 'cases': len(rows),
               'passed': sum(row['passed'] for row in rows),
               'pass_rate': sum(row['passed'] for row in rows) / len(rows),
               'end_to_end_p50_ms': percentile(.5), 'end_to_end_p95_ms': percentile(.95),
               'real_model_quality': 'not_measured', 'real_provider_cost_usd': None,
               'notes': 'Local SQLite + mock images. No real model quality, billing or production latency claim.',
               'results': rows}
    target = Path('evals/latest.json')
    target.write_text(json.dumps(summary, ensure_ascii=False, indent=2) + '\n')
    print(json.dumps({key: value for key, value in summary.items() if key != 'results'}, ensure_ascii=False, indent=2))
    if summary['passed'] != summary['cases']:
        raise SystemExit(1)


if __name__ == '__main__':
    main()
