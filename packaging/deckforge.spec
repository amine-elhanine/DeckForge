# PyInstaller spec for the DeckForge desktop application.
#
#     pyinstaller packaging/deckforge.spec --noconfirm
#
# Produces a one-directory build (faster to start and far easier to sign and
# install than one-file, which re-extracts to a temp folder on every launch).
#
# Everything the app reads at runtime is bundled under `deckforge/` inside the
# archive, which is exactly where `deckforge.paths.resource_root()` looks when
# `sys.frozen` is set.

import os
import sys
from pathlib import Path

from PyInstaller.utils.hooks import collect_submodules

# A windowed build has nowhere to print a traceback, which makes a startup
# crash undiagnosable. Set DECKFORGE_BUILD_CONSOLE=1 to attach a console.
CONSOLE = os.environ.get("DECKFORGE_BUILD_CONSOLE") == "1"

SPEC_DIR = Path(SPECPATH).resolve()
ROOT = SPEC_DIR.parent
BACKEND = ROOT / "backend"
WEB = ROOT / "frontend" / "out"

if not (WEB / "index.html").is_file():
    raise SystemExit(
        "The frontend has not been exported.\n"
        "Run `npm --prefix frontend ci && npm --prefix frontend run build` first."
    )

datas = [
    (str(BACKEND / "src" / "deckforge" / "themes" / "packages"), "deckforge/themes/packages"),
    (str(WEB), "deckforge/web"),
]

# Ship the example plugin so the plugin system is demonstrably live in the
# installed app, not just in a checkout.
if (ROOT / "plugins").is_dir():
    datas.append((str(ROOT / "plugins"), "deckforge/plugins"))

hiddenimports = [
    # Imported by name through the SQLAlchemy URL, so nothing references them.
    "aiosqlite",
    "sqlalchemy.dialects.sqlite.aiosqlite",
    # Uvicorn resolves its loop/protocol implementations at runtime.
    *collect_submodules("uvicorn"),
    # Provider adapters and exporters are reached through registries.
    *collect_submodules("deckforge.providers"),
    *collect_submodules("deckforge.exporters"),
    *collect_submodules("deckforge.retrieval"),
    "pptx",
    "fpdf",
    "pypdf",
    "docx",
    "openpyxl",
    "PIL.Image",
]

excludes = [
    "tkinter",
    "matplotlib",
    "numpy",
    "pandas",
    "scipy",
    "IPython",
    "pytest",
    "mypy",
    "ruff",
    "PyInstaller",
]

analysis = Analysis(
    [str(SPEC_DIR / "entry.py")],
    pathex=[str(BACKEND / "src")],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=excludes,
    noarchive=False,
    optimize=0,
)

pyz = PYZ(analysis.pure)

exe = EXE(
    pyz,
    analysis.scripts,
    [],
    exclude_binaries=True,
    name="DeckForge",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    # No console window: this is a windowed application.
    console=CONSOLE,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=str(SPEC_DIR / "assets" / "icon.ico"),
)

collect = COLLECT(
    exe,
    analysis.binaries,
    analysis.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name="DeckForge",
)

# macOS only: wrap the collected directory in a real .app bundle. BUNDLE is a
# no-op elsewhere, but it would still demand an .icns that other platforms
# cannot produce, so it is skipped entirely.
if sys.platform == "darwin":
    icns = SPEC_DIR / "assets" / "icon.icns"
    app = BUNDLE(
        collect,
        name="DeckForge.app",
        icon=str(icns) if icns.is_file() else None,
        bundle_identifier="dev.deckforge.app",
        info_plist={
            "CFBundleName": "DeckForge",
            "CFBundleDisplayName": "DeckForge",
            "CFBundleShortVersionString": "0.1.0",
            "NSHighResolutionCapable": True,
            "LSMinimumSystemVersion": "11.0",
        },
    )
