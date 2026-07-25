"""Build the portable Windows release:  python scripts/build.py

Produces dist/stt-dictation/ (the folder you can run from anywhere) and
dist/stt-dictation-<version>-win64.zip (what gets attached to a GitHub release).

Must run on Windows with the runtime dependencies installed, since PyInstaller
collects what it finds in the current environment:

    pip install -e ".[windows,build]"
"""

from __future__ import annotations

import shutil
import subprocess
import sys
import zipfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
SPEC = REPO / "packaging" / "stt.spec"
DIST = REPO / "dist"
BUILD = REPO / "build"


def _version() -> str:
    sys.path.insert(0, str(REPO / "src"))
    from stt import __version__

    return __version__


def _human(size: int) -> str:
    return f"{size / 1_048_576:.0f} MB"


def _zip(folder: Path, target: Path) -> None:
    """Zip ``folder`` so it extracts as a single top-level directory."""
    with zipfile.ZipFile(target, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as zf:
        for path in sorted(folder.rglob("*")):
            if path.is_file():
                zf.write(path, Path(folder.name) / path.relative_to(folder))


def main() -> int:
    if sys.platform != "win32":
        print("The release has to be built on Windows: PyInstaller bundles the "
              "binaries of the platform it runs on.", file=sys.stderr)
        return 1

    version = _version()
    print(f"Building STT Dictation {version}\n")

    # Regenerate the icon so the executable never ships a stale one.
    subprocess.run([sys.executable, str(REPO / "scripts" / "make_icon.py")], check=True)

    for stale in (BUILD, DIST / "stt-dictation"):
        if stale.exists():
            shutil.rmtree(stale)

    subprocess.run(
        [sys.executable, "-m", "PyInstaller", "--noconfirm", "--clean", str(SPEC)],
        cwd=REPO, check=True,
    )

    folder = DIST / "stt-dictation"
    exe = folder / "stt.exe"
    if not exe.exists():
        print(f"Build finished but {exe} is missing.", file=sys.stderr)
        return 1

    total = sum(p.stat().st_size for p in folder.rglob("*") if p.is_file())
    archive = DIST / f"stt-dictation-{version}-win64.zip"
    archive.unlink(missing_ok=True)
    print(f"\nZipping {_human(total)} into {archive.name}…")
    _zip(folder, archive)

    print(f"\n  folder : {folder}  ({_human(total)})")
    print(f"  archive: {archive}  ({_human(archive.stat().st_size)})")
    print("\nTo check it: run dist\\stt-dictation\\stt.exe and look for the "
          "microphone in the tray.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
