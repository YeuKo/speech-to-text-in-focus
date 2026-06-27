"""Seguimiento del coste estimado del uso de la API de transcripción.

El coste es una **estimación** basada en la duración del audio enviado y en las
tarifas (USD/minuto) configuradas, no el importe real facturado por OpenAI
(que no se devuelve en la respuesta). Cada transcripción se acumula en un CSV
para poder revisar el histórico y el total gastado.
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
            log.debug("No se pudo leer el historial de uso: %s", exc)
        return total

    def estimate(self, model: str, seconds: float) -> float | None:
        """Coste estimado en la moneda configurada, o None si no hay tarifa."""
        rate = self._rates.get(model)
        if rate is None:
            return None
        return seconds / 60.0 * rate

    def record(self, model: str, seconds: float) -> float | None:
        """Estima, registra en el CSV, actualiza el total y lo deja en el log."""
        cost = self.estimate(model, seconds)
        if cost is None:
            log.info("No hay tarifa configurada para '%s'; no se estima coste.", model)
            return None

        with self._lock:
            self._total += cost
            total = self._total
            self._append_row(model, seconds, cost)

        log.info(
            "Coste estimado: $%.4f (%.1fs, %s) | Acumulado: $%.4f %s",
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
            log.warning("No se pudo escribir el historial de uso: %s", exc)


__all__ = ["UsageTracker"]
