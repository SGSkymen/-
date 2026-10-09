import os

block_cipher = None
PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(SPEC), ".."))

datas = [
    (os.path.join(PROJECT_ROOT, "frontend", "templates"), "frontend/templates"),
    (os.path.join(PROJECT_ROOT, "frontend", "static"), "frontend/static"),
    (os.path.join(PROJECT_ROOT, "assets", "vtb.ico"), "assets"),
]
base_model_src = os.path.join(PROJECT_ROOT, "assets", "base_model.txt")
if os.path.exists(base_model_src):
    datas.append((base_model_src, "assets"))

a = Analysis(
    [os.path.join(PROJECT_ROOT, "main.py")],
    pathex=[PROJECT_ROOT],
    binaries=[],
    datas=datas,
    hiddenimports=[
        "lightgbm",
        "sklearn.utils._typedefs",
        "sklearn.neighbors._partition_nodes",
        "imblearn.over_sampling",
        "webview.platforms.winforms",
        "webview.platforms.edgechromium",
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.zipfiles,
    a.datas,
    [],
    name="VTB_Analytics",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,          # без консольного окна — только GUI
    disable_windowed_traceback=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=os.path.join(PROJECT_ROOT, "assets", "vtb.ico"),
)
