# setup_helper_user.spec

a = Analysis(
    ['setup_helper_user.py'], 
    pathex=[], 
    binaries=[], 
    datas=[],
    hiddenimports=[], 
    hookspath=[], 
    runtime_hooks=[], 
    excludes=[]
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz, 
    a.scripts, 
    a.binaries, 
    a.datas, 
    name='setup_helper_user',
    debug=False, 
    strip=False, 
    upx=True, 
    console=True
)