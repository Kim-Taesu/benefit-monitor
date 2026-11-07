"""Stage the static app plus unchanged public JSON/Markdown. No network or dependencies."""
import argparse
import shutil
import tempfile
from pathlib import Path


def assemble(root):
    root = Path(root).resolve()
    build = root / 'frontend/dist'
    public = root / 'delivery/public'
    output = root / 'delivery/site'
    if not (build / 'index.html').is_file():
        raise ValueError('Build frontend first')
    files = list(build.rglob('*'))
    for path in files:
        relative = path.relative_to(build)
        if path.is_symlink() or not (path.is_dir() and relative == Path('assets') or path.is_file() and (relative in (Path('index.html'), Path('admin.html')) or len(relative.parts) == 2 and relative.parts[0] == 'assets' and path.suffix in ('.js', '.css'))):
            raise ValueError('Unexpected frontend build file')
    if any(not (public / name).is_file() or (public / name).is_symlink() for name in ('briefing.json', 'briefing.md')):
        raise ValueError('Generate public briefing before staging')
    if output.is_symlink():
        raise ValueError('Staging output cannot be a symlink')
    # Validate before replacing the dedicated build directory; public exports stay untouched.
    with tempfile.TemporaryDirectory(prefix='.frontend-', dir=root / 'delivery') as tmp:
        staged = Path(tmp) / 'site'
        shutil.copytree(build, staged)
        for name in ('briefing.json', 'briefing.md'):
            shutil.copyfile(public / name, staged / name)
        if output.exists():
            shutil.rmtree(output)
        staged.rename(output)
    return output


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, default=Path(__file__).resolve().parents[1])
    print(assemble(parser.parse_args().root))
