"""Generate the frontend's public allowlists from local configuration, without network access."""
import argparse
import json
import os
import re
import tempfile
from pathlib import Path


def generate(root, check=False):
    root = Path(root)
    config = json.loads((root / 'sources.yaml').read_text(encoding='utf-8'))
    districts = json.loads((root / 'districts.json').read_text(encoding='utf-8'))
    if not isinstance(config, dict) or not isinstance(districts, dict):
        raise ValueError('Invalid source policy input')
    age = config.get('max_age_days')
    rows = config.get('sources')
    areas = districts.get('districts')
    if type(age) is not int or age <= 0 or not isinstance(rows, list) or not rows or not isinstance(areas, list) or not areas:
        raise ValueError('Invalid source policy input')
    sources = {}
    for row in rows:
        if not isinstance(row, dict):
            raise ValueError('Invalid source policy input')
        key = row.get('id')
        name = row.get('name', key)
        domains = row.get('domains')
        if not isinstance(key, str) or not re.fullmatch(r'[a-z][a-z0-9_]*', key) or key in sources or not isinstance(name, str) or not name.strip():
            raise ValueError('Invalid source policy input')
        if not isinstance(domains, list) or not domains:
            raise ValueError('Invalid source policy input')
        for host in domains:
            if not isinstance(host, str) or len(host) > 253 or not re.fullmatch(r'[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?(?:\.[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?)*', host):
                raise ValueError('Invalid source policy input')
        if len(set(domains)) != len(domains):
            raise ValueError('Invalid source policy input')
        sources[key] = {'name': name, 'domains': domains}
    names = []
    for area in areas:
        name = area.get('name') if isinstance(area, dict) else None
        if not isinstance(name, str) or not name.strip() or name in names:
            raise ValueError('Invalid source policy input')
        names.append(name)
    content = (json.dumps({'maxAgeDays': age, 'sources': sources, 'districts': names}, ensure_ascii=False, indent=2) + '\n').encode('utf-8')
    output = root / 'frontend/src/source-policy.json'
    if output.is_symlink():
        raise ValueError('Source policy output cannot be a symlink')
    if check:
        if not output.is_file() or output.read_bytes() != content:
            raise ValueError('Source policy is stale; run python scripts/generate_source_policy.py')
        return
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(dir=output.parent, prefix='.source-policy-', delete=False) as stream:
            temporary = Path(stream.name)
            stream.write(content)
        os.replace(temporary, output)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument('--check', action='store_true', help='Fail on missing or stale policy without writing')
    args = parser.parse_args()
    try:
        generate(args.root, args.check)
    except ValueError as error:
        parser.exit(1, f'{error}\n' if not isinstance(error, json.JSONDecodeError) else 'Invalid source policy input\n')
    except OSError:
        parser.exit(1, 'Cannot read or write source policy files\n')
