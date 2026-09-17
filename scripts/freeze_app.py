"""Pin only this app's installed dependency closure, excluding host tools."""
from importlib.metadata import distribution
from pathlib import Path
import tomllib
from packaging.requirements import Requirement
from packaging.utils import canonicalize_name

root = Path(__file__).resolve().parents[1]
project = tomllib.loads((root / 'pyproject.toml').read_text())['project']
queue = [Requirement(item) for item in project['dependencies'] + project['optional-dependencies']['dev']]
seen = {}
while queue:
    requirement = queue.pop()
    if requirement.marker and not requirement.marker.evaluate():
        continue
    key = canonicalize_name(requirement.name)
    if key in seen:
        continue
    dist = distribution(requirement.name)
    seen[key] = f'{dist.metadata["Name"]}=={dist.version}'
    for dep in dist.requires or []:
        parsed = Requirement(dep)
        contexts = [{'extra': extra} for extra in requirement.extras] or [{'extra': ''}]
        if not parsed.marker or any(parsed.marker.evaluate(context) for context in contexts):
            parsed.marker = None
            queue.append(parsed)
(root / 'dashboard/requirements-lock.txt').write_text('\n'.join(seen[k] for k in sorted(seen)) + '\n', encoding='utf-8')
print(f'Pinned {len(seen)} application dependencies.')
