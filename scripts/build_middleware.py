from __future__ import annotations

import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
DIST_DIR = ROOT / 'dist' / 'middleware'
BUILD_DIR = ROOT / 'build' / 'middleware'
SPEC_PATH = ROOT / 'hrms-middleware-bridge.spec'
EXE_NAME = 'hrms-middleware-bridge'


def main() -> None:
    DIST_DIR.mkdir(parents=True, exist_ok=True)
    BUILD_DIR.mkdir(parents=True, exist_ok=True)
    if not SPEC_PATH.exists():
        raise SystemExit(f'PyInstaller spec file not found: {SPEC_PATH}')
    command = [
        sys.executable,
        '-m',
        'PyInstaller',
        '--noconfirm',
        '--clean',
        '--distpath',
        str(DIST_DIR),
        '--workpath',
        str(BUILD_DIR),
        str(SPEC_PATH),
    ]
    subprocess.run(command, check=True, cwd=ROOT)
    artifact = DIST_DIR / (f'{EXE_NAME}.exe' if sys.platform.startswith('win') else EXE_NAME)
    print(f'Middleware bridge built at: {artifact}')


if __name__ == '__main__':
    main()
