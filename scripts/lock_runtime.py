"""Record the installed runtime dependency closure for Linux/Python 3.12 builds."""
from importlib.metadata import distribution
from pathlib import Path

from packaging.requirements import Requirement
from packaging.utils import canonicalize_name

root = Path(__file__).resolve().parents[1]
pending = [Requirement(line) for line in (root / 'requirements.txt').read_text().splitlines()
           if line.strip() and not line.startswith('#')]
visited = {}
versions = {}
while pending:
    requirement = pending.pop()
    name = canonicalize_name(requirement.name)
    extras = set(requirement.extras)
    if name in visited and extras <= visited[name]:
        continue
    visited.setdefault(name, set()).update(extras)
    package = distribution(name)
    versions[name] = package.version
    for dependency in package.requires or []:
        child = Requirement(dependency)
        if child.marker is None or any(child.marker.evaluate({'extra': extra}) for extra in visited[name] | {''}):
            pending.append(child)
lines = ['# Generated from installed runtime closure on Linux / Python 3.12; no hashes.']
lines += [f'{name}=={version}' for name, version in sorted(versions.items())]
(root / 'requirements-runtime.lock').write_text('\n'.join(lines) + '\n')
print(f'Locked {len(versions)} runtime packages')
