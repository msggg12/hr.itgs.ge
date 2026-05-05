from __future__ import annotations

import os
import sys
import traceback
from pathlib import Path


def _crash_report_path() -> Path:
    base = Path(os.environ.get('HRMS_BRIDGE_LOG_DIR') or Path.cwd())
    return base / 'hrms-middleware-bridge-crash.log'


def _pause_for_operator() -> None:
    if os.environ.get('HRMS_BRIDGE_NO_PAUSE') == '1':
        return
    try:
        input('Middleware bridge stopped. Press Enter to close this window...')
    except EOFError:
        pass


def main() -> int:
    try:
        from app.middleware_bridge import main as bridge_main

        return int(bridge_main())
    except SystemExit as exc:
        code = exc.code if isinstance(exc.code, int) else 1
        if code:
            traceback.print_exc()
            _pause_for_operator()
        return code
    except Exception:
        stack = traceback.format_exc()
        print(stack, file=sys.stderr)
        try:
            path = _crash_report_path()
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(stack, encoding='utf-8')
            print(f'Crash report written to: {path}', file=sys.stderr)
        except Exception:
            traceback.print_exc()
        _pause_for_operator()
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
