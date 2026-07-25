# PyInstaller build: a portable Windows folder, zipped for release.
#
# Run it through scripts/build.py, which passes the repo root in and zips the
# result. Deliberate choices:
#
# - onedir, not onefile. A onefile build unpacks ~250 MB into a temporary folder
#   on *every* launch, adding seconds to each start of a tray app that is meant to
#   sit there quietly.
# - console=False. It is a tray app; a console window would be noise. Everything
#   goes to the log instead, and startup failures pop up a dialog (see _fatal).
# - No CUDA libraries bundled. cuBLAS alone is 100 MB and cuDNN much more. The app
#   already uses the GPU when the machine has the CUDA 12.x runtime and falls back
#   to CPU when it does not.
# - No model bundled. faster-whisper downloads it on first use and caches it in
#   %USERPROFILE%\.cache\huggingface; the app now says so while it happens.

from pathlib import Path

REPO = Path(SPECPATH).parent          # noqa: F821  (SPECPATH is injected)
VERSION_FILE = REPO / "packaging" / "version_info.txt"

a = Analysis(
    [str(REPO / "src" / "stt" / "__main__.py")],
    pathex=[str(REPO / "src")],
    binaries=[],
    datas=[
        # The template the app copies to config.toml on a first run.
        (str(REPO / "config.example.toml"), "."),
        (str(REPO / "assets" / "stt.ico"), "assets"),
        (str(REPO / "README.md"), "."),
        (str(REPO / "LICENSE"), "."),
    ],
    hiddenimports=[
        # Chosen at runtime by keyring, so the import graph cannot see them.
        "keyring.backends.Windows",
        "keyring.backends.fail",
    ],
    hookspath=[],
    runtime_hooks=[],
    excludes=[
        # Heavyweights that are not used but get pulled in by association.
        "torch", "torchaudio", "transformers", "matplotlib", "pandas", "scipy",
        "IPython", "pytest", "setuptools", "tkinter.test", "test",
    ],
    noarchive=False,
)

pyz = PYZ(a.pure)                     # noqa: F821

exe = EXE(                            # noqa: F821
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="stt",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,                        # UPX-packed DLLs trip antivirus heuristics
    console=False,
    disable_windowed_traceback=False,
    icon=str(REPO / "assets" / "stt.ico"),
    version=str(VERSION_FILE) if VERSION_FILE.exists() else None,
)

coll = COLLECT(                       # noqa: F821
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    name="stt-dictation",
)
