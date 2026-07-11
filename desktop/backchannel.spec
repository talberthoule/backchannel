# PyInstaller spec for the Backchannel desktop bundle (one-dir).
import sys
from pathlib import Path

from PyInstaller.utils.hooks import collect_submodules

repo = Path(SPECPATH).parent

# Make the backend package importable for collect_submodules on clean machines.
sys.path.insert(0, str(repo / "backend"))

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

a = Analysis(
    [str(repo / "desktop" / "launcher.py")],
    pathex=[str(repo / "backend"), str(repo / "desktop")],
    datas=[
        (str(repo / "frontend" / "dist"), "frontend"),
        (str(repo / "backend" / "models"), "models"),
        (str(repo / "desktop" / "pgsql"), "pgsql"),
    ],
    hiddenimports=hidden,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    exclude_binaries=True,
    name="Backchannel",
    console=False,
)

coll = COLLECT(exe, a.binaries, a.datas, name="Backchannel")

if sys.platform == "darwin":
    app = BUNDLE(
        coll,
        name="Backchannel.app",
        bundle_identifier="io.github.backchannel",
        # Menu-bar (tray) app: no Dock icon.
        info_plist={"LSUIElement": True},
    )
