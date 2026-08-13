# setup_helper.spec — PyInstaller spec for the setup helper exe
#
# Build with:
#   pyinstaller installer/setup_helper.spec

a = Analysis(
    ['setup_helper.py'],
    pathex=[],
    binaries=[],
    datas=[],
    hiddenimports=['keyring'],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    name='setup_helper',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=True,    # console=True so the installer can capture output
)
