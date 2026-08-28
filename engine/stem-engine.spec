from PyInstaller.utils.hooks import collect_all, collect_submodules

datas = []
binaries = []
hiddenimports = []

for package in (
    "demucs",
    "bs_roformer",
    "torch",
    "torchaudio",
    "soundfile",
    "julius",
    "basic_pitch",
    "torchcrepe",
    "coremltools",
    "librosa",
    "mido",
    "drumscript",
):
    package_datas, package_binaries, package_hidden = collect_all(package)
    if package == "torchcrepe":
        package_datas = [
            entry for entry in package_datas if not str(entry[0]).endswith("full.pth")
        ]
    datas += package_datas
    binaries += package_binaries
    hiddenimports += package_hidden

hiddenimports += collect_submodules("demucs")

analysis = Analysis(
    ["main.py"],
    pathex=[],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
)
pyz = PYZ(analysis.pure)
exe = EXE(
    pyz,
    analysis.scripts,
    [],
    exclude_binaries=True,
    name="stem-engine",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=True,
    target_arch="arm64",
    codesign_identity=None,
)
coll = COLLECT(
    exe,
    analysis.binaries,
    analysis.datas,
    strip=False,
    upx=False,
    name="stem-engine",
)
