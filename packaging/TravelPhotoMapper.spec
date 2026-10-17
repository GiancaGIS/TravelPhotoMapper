# -*- mode: python ; coding: utf-8 -*-

from pathlib import Path

project_root = Path(SPECPATH).parent
source_root = project_root / "src"
package_root = source_root / "travel_photo_mapper"

a = Analysis(
    [str(package_root / "main.py")],
    pathex=[str(source_root)],
    binaries=[],
    datas=[(str(package_root / "assets" / "travel_photo_mapper.png"), "assets")],
    hiddenimports=[],
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
    name="TravelPhotoMapper",
    icon=str(package_root / "assets" / "travel_photo_mapper.ico"),
    version=str(project_root / "packaging" / "version_info.txt"),
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
