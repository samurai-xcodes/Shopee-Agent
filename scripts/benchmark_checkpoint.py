"""Controlled mock comparison: naive regeneration vs actual persisted approval resume."""
import json
from pathlib import Path
import tempfile
import time

from fastapi.testclient import TestClient

from database import migrate
from main import create_app
from providers import MockProvider
from settings import Settings
from storage import AssetStore
from worker import run_once


class CountingProvider(MockProvider):
    calls = 0
    def image(self, brief, index):
        self.calls += 1
        return super().image(brief, index)


def main():
    with tempfile.TemporaryDirectory(prefix='shopee-benchmark-') as directory:
        settings = Settings(database_url=f'sqlite:///{directory}/app.db',
                            storage_dir=Path(directory) / 'assets', checkpoint_path=f'{directory}/checkpoints.db')
        app = create_app(settings)
        migrate(app.state.engine)
        provider = CountingProvider()
        with TestClient(app, headers={'X-Dev-User': 'benchmark'}) as client:
            task = client.post('/tasks', json={'prompt': 'shoe poster'}).json()
            path = '/tasks/' + task['task_id']
            run_once(settings, app.state.sessions, provider)
            version = client.get(path + '/versions').json()[0]
            # Explicit experimental baseline, not a claim about earlier production code.
            provider.calls = 0
            started = time.perf_counter()
            store = AssetStore(settings.storage_dir)
            for index in range(3):
                store.put(provider.image(provider.parse('shoe poster'), index))
            baseline = {'image_calls': provider.calls, 'latency_ms': round((time.perf_counter() - started) * 1000, 2)}
            provider.calls = 0
            client.post(path + '/approve', json={'version_id': version['version_id']})
            started = time.perf_counter()
            run_once(settings, app.state.sessions, provider)
            resumed = {'image_calls': provider.calls, 'latency_ms': round((time.perf_counter() - started) * 1000, 2)}
            assert client.get(path).json()['status'] == 'SUCCESS'
            assert baseline['image_calls'] == 3 and resumed['image_calls'] == 0
    result = {'mode': 'controlled_mock_comparison', 'naive_regeneration_baseline': baseline,
              'persisted_approval_resume': resumed,
              'limitations': 'Synthetic naive baseline, local mock provider. No real API cost or production performance claim.'}
    Path('evals/checkpoint_comparison.json').write_text(json.dumps(result, indent=2) + '\n')
    print(json.dumps(result, indent=2))


if __name__ == '__main__':
    main()
