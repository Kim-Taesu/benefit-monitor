"""Generate the operational sources.yaml from sources/<id>.json definitions, without network access."""
import argparse
import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from benefit_monitor.source_registry import render  # noqa: E402


def generate(root, check=False):
    root = Path(root)
    content = render(root).encode('utf-8')
    output = root / 'sources.yaml'
    if output.is_symlink():
        raise ValueError('sources.yaml cannot be a symlink')
    if check:
        if not output.is_file() or output.read_bytes() != content:
            raise ValueError('sources.yaml is stale; edit sources/<id>.json and run python scripts/generate_sources.py')
        return
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(dir=root, prefix='.sources-', delete=False) as stream:
            temporary = Path(stream.name)
            stream.write(content)
        os.replace(temporary, output)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument('--check', action='store_true', help='Fail on stale sources.yaml without writing')
    args = parser.parse_args()
    try:
        generate(args.root, args.check)
    except ValueError as error:
        parser.exit(1, f'{error}\n')
