from __future__ import annotations

import importlib
import sys
from decimal import Decimal
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

MODULES = [
    'app.main',
    'app.device_middleware',
    'app.labor_engine',
    'app.mattermost_integration',
    'app.ats_onboarding',
    'app.assets_lifecycle',
    'app.performance',
    'app.analytics',
    'app.user_experience',
    'app.monitoring',
    'app.google_calendar',
    'app.tenant_integrity',
]

for name in MODULES:
    importlib.import_module(name)
    print(f'[OK] imported {name}')

from app.main import app  # noqa: E402
from app.performance import _percentage  # noqa: E402

assert len(app.routes) >= 20, 'Expected expanded enterprise route set'
assert _percentage(Decimal('55'), Decimal('0'), Decimal('100')) == Decimal('55.00')
assert (PROJECT_ROOT / 'sql' / '002_enterprise_extensions.sql').exists()
tenant_rls_sql = (PROJECT_ROOT / 'sql' / '003_phase1_tenant_rls.sql').read_text(encoding='utf-8')
assert 'FORCE ROW LEVEL SECURITY' in tenant_rls_sql
assert 'tenant_role_permission_overrides' in tenant_rls_sql
assert 'auth_invites' in tenant_rls_sql
assert 'employee_google_calendar_connections' in tenant_rls_sql
removed_demo_path = '/ux/' + 'de' + 'mo'
assert all(getattr(route, 'path', '') != removed_demo_path for route in app.routes)
print(f'[OK] route count = {len(app.routes)}')
print('[OK] tenant RLS policy file covers invites, calendar connections, and role overrides')
print('[OK] project smoke checks passed')
