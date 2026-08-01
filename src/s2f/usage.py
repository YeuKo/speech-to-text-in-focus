"""Estimated cost tracking for transcription API usage.

The cost is an **estimate** based on the duration of the audio sent and the
configured rates (USD/minute), not the exact amount billed by OpenAI (which is
not returned in the response). Each transcription is appended to a CSV so the
history and running total can be reviewed.
"""

from __future__ import annotations

import csv
import datetime as _dt
import logging
import threading
from pathlib import Path

log = logging.getLogger(__name__)


class UsageTracker:
    def __init__(
        self,
        file_path: str | Path,
        price_per_min: dict[str, float],
        currency: str = "USD",
    ) -> None:
        self._path = Path(file_path)
        self._rates = price_per_min
        self._currency = currency
        self._lock = threading.Lock()
        self._total = self._load_total()

    @property
    def total(self) -> float:
        return self._total

    def _load_total(self) -> float:
        if not self._path.exists():
            return 0.0
        total = 0.0
        try:
            with self._path.open(newline="", encoding="utf-8") as fh:
                for row in csv.DictReader(fh):
                    try:
                        total += float(row.get("cost", 0))
                    except (TypeError, ValueError):
                        continue
        except OSError as exc:
            log.debug("Could not read the usage history: %s", exc)
        return total

    def estimate(self, model: str, seconds: float) -> float | None:
        """Estimated cost in the configured currency, or None if no rate."""
        rate = self._rates.get(model)
        if rate is None:
            return None
        return seconds / 60.0 * rate

    def record(self, model: str, seconds: float) -> float | None:
        """Estimate, append to the CSV, update the total and log it."""
        cost = self.estimate(model, seconds)
        if cost is None:
            log.info("No rate configured for '%s'; skipping cost estimate.", model)
            return None

        with self._lock:
            self._total += cost
            total = self._total
            self._append_row(model, seconds, cost)

        log.info(
            "Estimated cost: $%.4f (%.1fs, %s) | Total: $%.4f %s",
            cost, seconds, model, total, self._currency,
        )
        return cost

    def _append_row(self, model: str, seconds: float, cost: float) -> None:
        is_new = not self._path.exists()
        try:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            with self._path.open("a", newline="", encoding="utf-8") as fh:
                writer = csv.writer(fh)
                if is_new:
                    writer.writerow(["timestamp", "model", "seconds", "cost"])
                writer.writerow([
                    _dt.datetime.now().isoformat(timespec="seconds"),
                    model,
                    f"{seconds:.2f}",
                    f"{cost:.6f}",
                ])
        except OSError as exc:
            log.warning("Could not write the usage history: %s", exc)


__all__ = ["UsageTracker"]
