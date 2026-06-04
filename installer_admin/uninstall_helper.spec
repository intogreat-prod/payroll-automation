# uninstall_helper.spec — PyInstaller spec for the uninstall cleanup exe
#
# Build with:
#   pyinstaller installer/uninstall_helper.spec

a = Analysis(
    ['uninstall_helper.py'],
    pathex=[],
    binaries=[],
    datas=[],
    hiddenimports=['keyring.backends.Windows'],
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
    name='uninstall_helper',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=True,
    uac_admin=True,
)
