from __future__ import annotations

import argparse
import asyncio
import ctypes
import logging
import os
import sys
import time
from pathlib import Path
from typing import Iterable

from app.db import Database
from app.device_middleware import ingest_logs_once


LOGGER = logging.getLogger('hrms.middleware_bridge')


class Ansi:
    RESET = '\033[0m'
    DIM = '\033[2m'
    RED = '\033[31m'
    GREEN = '\033[32m'
    YELLOW = '\033[33m'
    BLUE = '\033[34m'
    MAGENTA = '\033[35m'
    CYAN = '\033[36m'
    BOLD = '\033[1m'


class ColorFormatter(logging.Formatter):
    COLORS = {
        logging.DEBUG: Ansi.DIM,
        logging.INFO: Ansi.CYAN,
        logging.WARNING: Ansi.YELLOW,
        logging.ERROR: Ansi.RED,
        logging.CRITICAL: Ansi.BOLD + Ansi.RED,
    }

    def format(self, record: logging.LogRecord) -> str:
        level_color = self.COLORS.get(record.levelno, '')
        record.levelname = f'{level_color}{record.levelname:<8}{Ansi.RESET}'
        return super().format(record)


def enable_windows_ansi() -> None:
    if os.name != 'nt':
        return
    kernel32 = ctypes.windll.kernel32
    handle = kernel32.GetStdHandle(-11)
    mode = ctypes.c_uint()
    if kernel32.GetConsoleMode(handle, ctypes.byref(mode)):
        kernel32.SetConsoleMode(handle, mode.value | 0x0004)


def configure_logging(verbose: bool = False) -> None:
    enable_windows_ansi()
    handler = logging.StreamHandler()
    handler.setFormatter(ColorFormatter('%(asctime)s %(levelname)s %(message)s', '%Y-%m-%d %H:%M:%S'))
    root = logging.getLogger()
    root.handlers.clear()
    root.addHandler(handler)
    root.setLevel(logging.DEBUG if verbose else logging.INFO)


def load_env_file(path: Path | None) -> None:
    if path is None:
        return
    if not path.exists():
        LOGGER.warning('Env file not found: %s', path)
        return
    for raw_line in path.read_text(encoding='utf-8').splitlines():
        line = raw_line.strip()
        if not line or line.startswith('#') or '=' not in line:
            continue
        key, value = line.split('=', 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        os.environ.setdefault(key, value)
    LOGGER.info('Loaded env file: %s', path)


def first_env(keys: Iterable[str], default: str = '') -> str:
    for key in keys:
        value = os.environ.get(key)
        if value:
            return value
    return default


def resolve_database_url() -> str:
    database_url = first_env(('DATABASE_URL', 'CENTRAL_DATABASE_URL'))
    if not database_url:
        raise RuntimeError('DATABASE_URL or CENTRAL_DATABASE_URL is required')
    return database_url


async def bridge_loop(poll_seconds: int) -> None:
    db = Database(resolve_database_url())
    await db.connect()
    LOGGER.info('%sHRMS Middleware Bridge started%s', Ansi.GREEN, Ansi.RESET)
    LOGGER.info('Polling devices every %s seconds', poll_seconds)
    try:
        while True:
            started = time.monotonic()
            try:
                totals = await ingest_logs_once(db)
                inserted = sum(totals.values())
                if totals:
                    detail = ', '.join(f'{name}={count}' for name, count in totals.items())
                else:
                    detail = 'no active devices'
                LOGGER.info('%sheartbeat%s sync=%s logs=%s %s', Ansi.GREEN, Ansi.RESET, len(totals), inserted, detail)
            except Exception:
                LOGGER.exception('%ssync failed; bridge will keep running%s', Ansi.RED, Ansi.RESET)
            elapsed = time.monotonic() - started
            await asyncio.sleep(max(1, poll_seconds - int(elapsed)))
    finally:
        await db.close()


def wait_for_operator() -> None:
    if os.environ.get('HRMS_BRIDGE_NO_PAUSE') == '1':
        return
    if not sys.stdin or not sys.stdin.isatty():
        return
    try:
        input(f'{Ansi.YELLOW}Press Enter to close the middleware console...{Ansi.RESET}')
    except EOFError:
        pass


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description='HRMS hardware middleware bridge')
    parser.add_argument('--env-file', default=os.environ.get('HRMS_BRIDGE_ENV_FILE', '.env.edge'), help='Path to middleware env file')
    parser.add_argument('--poll-seconds', type=int, default=int(os.environ.get('MIDDLEWARE_POLL_SECONDS', '30')))
    parser.add_argument('--verbose', action='store_true')
    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    configure_logging(args.verbose)
    env_file = Path(args.env_file).expanduser().resolve() if args.env_file else None
    try:
        load_env_file(env_file)
        asyncio.run(bridge_loop(max(args.poll_seconds, 5)))
    except KeyboardInterrupt:
        LOGGER.warning('Middleware bridge stopped by operator')
    except Exception:
        LOGGER.exception('Middleware bridge crashed before startup completed')
        wait_for_operator()
        return 1
    wait_for_operator()
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
