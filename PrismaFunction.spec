from PyInstaller.utils.hooks import collect_data_files, collect_submodules


playwright_hidden_imports = collect_submodules("playwright")
playwright_data = collect_data_files("playwright")

analysis = Analysis(
    ["app.py"],
    pathex=[],
    binaries=[],
    datas=playwright_data,
    hiddenimports=playwright_hidden_imports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    # Test/build tooling can be reached through optional pandas imports. It is
    # never required at runtime and must not make the release depend on the
    # developer environment.
    excludes=["pytest", "_pytest", "setuptools"],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(analysis.pure)

exe = EXE(
    pyz,
    analysis.scripts,
    [],
    exclude_binaries=True,
    name="PrismaFunction",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    version="PrismaFunction.version",
)
collection = COLLECT(
    exe,
    analysis.binaries,
    analysis.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name="PrismaFunction",
)
