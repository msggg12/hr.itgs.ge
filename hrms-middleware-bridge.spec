# -*- mode: python ; coding: utf-8 -*-

import os
from pathlib import Path

from PyInstaller.utils.hooks import collect_all


ROOT = Path.cwd()
AGENT = ROOT / 'middleware' / 'agent.py'

SDK_PATTERNS = (
    'plcommpro.dll',
    'commpro.dll',
    'comms.dll',
    'plcomms.dll',
    'plcommutils.dll',
    'pltcpcomm.dll',
    'plrscomm.dll',
    'plusbcomm.dll',
    'usbcomm.dll',
    'usbstd.dll',
    'libusb0.dll',
    'rscagent.dll',
    'plrscagent.dll',
    'ZK*.dll',
    '*zk*.dll',
    '*zkteco*.dll',
    '*dahua*.dll',
    '*Dahua*.dll',
    '*dh*.dll',
    '*DH*.dll',
    '*NetSDK*.dll',
    '*netsdk*.dll',
    'dhnetsdk.dll',
    'dhconfigsdk.dll',
)

SDK_SEARCH_DIRS = [
    ROOT / 'middleware',
    ROOT / 'sdk',
    ROOT / 'drivers',
    ROOT / 'deployment',
    Path('C:/ZKTeco/PullSDK'),
    Path('C:/ZKTeco'),
    Path('C:/Dahua'),
    Path('C:/Program Files/ZKTeco'),
    Path('C:/Program Files (x86)/ZKTeco'),
    Path('C:/Program Files/Dahua'),
    Path('C:/Program Files (x86)/Dahua'),
]

for extra_dir in os.environ.get('HRMS_SDK_DIRS', '').split(os.pathsep):
    if extra_dir.strip():
        SDK_SEARCH_DIRS.append(Path(extra_dir.strip()))


def discover_sdk_binaries():
    found = {}
    for directory in SDK_SEARCH_DIRS:
        if not directory.exists():
            continue
        include_zkteco_usb = os.environ.get('HRMS_INCLUDE_ZK_USB', '').strip().lower() in {'1', 'true', 'yes', 'on'}
        has_libusb = any(directory.rglob('libusb0.dll'))
        for pattern in SDK_PATTERNS:
            for path in directory.rglob(pattern):
                if path.is_file() and path.suffix.lower() in {'.dll', '.so', '.dylib', '.lib', '.bin'}:
                    if path.name.lower() in {'usbcomm.dll', 'usbstd.dll'} and not (include_zkteco_usb and has_libusb):
                        continue
                    found[str(path.resolve()).lower()] = (str(path.resolve()), '.')
    return sorted(found.values(), key=lambda item: item[0].lower())


datas = []
binaries = discover_sdk_binaries()
hiddenimports = ['pyodbc', 'sqlalchemy']

for package in ('sqlalchemy', 'pyodbc'):
    try:
        package_datas, package_binaries, package_hiddenimports = collect_all(package)
    except Exception:
        continue
    datas += package_datas
    binaries += package_binaries
    hiddenimports += package_hiddenimports

a = Analysis(
    [str(AGENT)],
    pathex=[str(ROOT)],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name='hrms-middleware-bridge',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=True,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
