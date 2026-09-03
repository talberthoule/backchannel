# PyInstaller spec for the Backchannel desktop bundle (one-dir).
import sys
from pathlib import Path

from PyInstaller.utils.hooks import collect_data_files, collect_submodules, copy_metadata

repo = Path(SPECPATH).parent

# Make the backend package importable for collect_submodules on clean machines.
sys.path.insert(0, str(repo / "backend"))
sys.path.insert(0, str(repo / "desktop"))

from app.release_notes import APP_VERSION  # noqa: E402
from scripts.version_resource import write_resource  # noqa: E402


def version_of(filename, description):
    """Windows version resource path, or None on platforms without one."""
    if sys.platform != "win32":
        return None
    return str(write_resource(workpath, APP_VERSION, filename, description))

hidden = collect_submodules("app") + [
    "uvicorn.logging",
    "uvicorn.loops.auto",
    "uvicorn.protocols.http.auto",
    "uvicorn.protocols.websockets.auto",
    "uvicorn.lifespan.on",
]
if sys.platform == "win32":
    hidden.append("pystray._win32")
elif sys.platform == "darwin":
    hidden.append("pystray._darwin")
else:
    hidden.append("pystray._xorg")

datas = [
    (str(repo / "frontend" / "dist"), "frontend"),
    (str(repo / "backend" / "models"), "models"),
    (str(repo / "desktop" / "pgsql"), "pgsql"),
    (str(repo / "desktop" / "assets"), "assets"),
    (str(repo / "desktop" / "release_signing_keys.json"), "."),
]
# Present only after desktop/scripts/download_ffmpeg.py runs (Windows/Linux
# releases); macOS bundles stay ffmpeg-free.
if (repo / "desktop" / "ffmpeg").is_dir():
    datas.append((str(repo / "desktop" / "ffmpeg"), "ffmpeg"))

# Packages that read their own installed version at import time. Without the
# dist-info, importlib.metadata raises PackageNotFoundError inside the bundle:
# onnx_asr does this on line 7 of its __init__, which broke every local
# transcription in shipped desktop builds until v0.6.2 (ALP-373).
for _distribution in ("onnx-asr", "huggingface-hub", "tqdm"):
    try:
        datas += copy_metadata(_distribution)
    except Exception as exc:  # noqa: BLE001 - a missing optional dep must not break the build
        print(f"backchannel.spec: no metadata for {_distribution}: {exc}")

# Packages that load their own data files at runtime through
# importlib.resources. PyInstaller freezes .py modules into the archive but
# leaves these behind unless they are collected explicitly, and the failure
# only shows up in a built bundle. onnx_asr's preprocessors read
# data/fbanks.npz and a set of .onnx front-end graphs, so without them every
# local transcription raises FileNotFoundError even though the package
# imports cleanly. That is what still broke local transcription in v0.6.2
# after copy_metadata fixed the layer above it (ALP-376).
for _package in ("onnx_asr",):
    collected = collect_data_files(_package)
    if not collected:
        raise SystemExit(
            f"backchannel.spec: no data files collected for {_package}; "
            "the bundle would ship without the files it reads at runtime"
        )
    datas += collected

a = Analysis(
    [str(repo / "desktop" / "launcher.py")],
    pathex=[str(repo / "backend"), str(repo / "desktop")],
    datas=datas,
    hiddenimports=hidden,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    exclude_binaries=True,
    name="Backchannel",
    console=False,
    icon=str(repo / "desktop" / "assets" / "icon.ico")
    if sys.platform == "win32"
    else None,
    version=version_of("Backchannel.exe", "Backchannel"),
)

updater_a = Analysis(
    [str(repo / "desktop" / "updater.py")],
    pathex=[str(repo / "desktop")],
)
updater_pyz = PYZ(updater_a.pure)
updater_exe = EXE(
    updater_pyz,
    updater_a.scripts,
    updater_a.binaries,
    updater_a.datas,
    [],
    name="BackchannelUpdater",
    console=False,
    icon=str(repo / "desktop" / "assets" / "icon.ico")
    if sys.platform == "win32"
    else None,
    version=version_of("BackchannelUpdater.exe", "Backchannel Updater"),
)

coll = COLLECT(
    exe,
    updater_exe,
    a.binaries,
    a.datas,
    name="Backchannel",
)

if sys.platform == "darwin":
    app = BUNDLE(
        coll,
        name="Backchannel.app",
        bundle_identifier="io.github.backchannel",
        icon=str(repo / "desktop" / "assets" / "icon.icns"),
        # Menu-bar (tray) app: no Dock icon.
        info_plist={"LSUIElement": True},
    )
