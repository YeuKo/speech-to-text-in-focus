"""Generate assets/stt.ico from the same microphone the tray draws.

Run after changing the icon shape:  python scripts/make_icon.py

The tray builds its image in memory, but the executable, its taskbar entry and any
shortcut need a real .ico file, with the sizes Windows picks from.
"""

from __future__ import annotations

import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))

from stt.ui.tray import _COLORS, _make_image  # noqa: E402

SIZES = [(256, 256), (48, 48), (32, 32), (24, 24), (16, 16)]


def main() -> int:
    target = REPO / "assets" / "stt.ico"
    target.parent.mkdir(parents=True, exist_ok=True)

    # Idle blue: the app at rest, which is how the icon is seen out of context.
    image = _make_image(_COLORS["idle"])
    image.save(target, format="ICO", sizes=SIZES)
    print(f"Wrote {target} ({target.stat().st_size} bytes, sizes: "
          f"{', '.join(f'{w}x{h}' for w, h in SIZES)})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
