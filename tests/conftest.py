import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
COTD_DIR = REPO.parent / 'zeepkist cotd elo'
sys.path.insert(0, str(REPO))

# Never copied into a scratch repo: history, caches, and big per-cup logs (each
# test copies only the logs it needs).
SKIP = {'.git', '__pycache__', 'old_status', 'backups', 'cup logs', 'tests', 'node_modules',
        'submit-worker'}


@pytest.fixture
def scratch(tmp_path):
    """A working copy of the repo (rankings sources, scripts, cup_meta.json)."""
    dst = tmp_path / 'petite'
    dst.mkdir()
    for item in REPO.iterdir():
        if item.name in SKIP or item.suffix == '.bak':
            continue
        if item.is_dir():
            shutil.copytree(item, dst / item.name)
        else:
            shutil.copy2(item, dst / item.name)
    (dst / 'cup logs').mkdir()
    return dst


def run_script(repo, *args):
    env = dict(os.environ, PETITE_SKIP_EXTERNAL='1', PETITE_COTD_DIR=str(COTD_DIR),
               PYTHONIOENCODING='utf-8')
    r = subprocess.run([sys.executable, *args], cwd=repo, env=env,
                       capture_output=True, text=True, encoding='utf-8')
    return r.returncode, r.stdout + r.stderr
