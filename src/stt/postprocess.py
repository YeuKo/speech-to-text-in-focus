"""Post-procesado de la transcripción: diccionario de términos y sustituciones.

Lógica pura (sin dependencias de Windows ni de modelos), por lo que es la parte
más fácil de testear. Dos mecanismos:

1. ``build_prompt``: genera el ``initial_prompt`` que se pasa a Whisper para
   sesgar el reconocimiento hacia los nombres propios del diccionario.
2. ``apply``: aplica sustituciones sobre el texto ya transcrito. Por defecto
   coincidencia exacta por palabra (sin distinguir mayúsculas). Si ``rapidfuzz``
   está instalado, ``apply_fuzzy`` añade corrección por similitud fonética.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping

_WORD_RE = re.compile(r"\w+", re.UNICODE)


def build_prompt(terms: Iterable[str]) -> str | None:
    """Construye el prompt de sesgo a partir de los términos del diccionario.

    Devuelve None si no hay términos, para no pasar un prompt vacío a Whisper.
    """
    cleaned = [t.strip() for t in terms if t and t.strip()]
    if not cleaned:
        return None
    return "Vocabulario: " + ", ".join(cleaned) + "."


def _match_case(source: str, replacement: str) -> str:
    """Ajusta el case del reemplazo al de la palabra original cuando tiene sentido.

    - Si el original va en MAYÚSCULAS, el reemplazo también.
    - Si el original empieza por mayúscula, se capitaliza el reemplazo.
    - En otro caso se respeta el reemplazo tal cual (útil para nombres propios
      como "Anthropic" o "Kubernetes", que ya traen su capitalización).
    """
    if source.isupper() and len(source) > 1:
        return replacement.upper()
    if source[:1].isupper() and replacement[:1].islower():
        return replacement[:1].upper() + replacement[1:]
    return replacement


def apply(text: str, replacements: Mapping[str, str]) -> str:
    """Aplica sustituciones exactas por palabra (sin distinguir mayúsculas).

    Las claves se comparan a nivel de palabra completa (con límites \\b), de modo
    que "anthropik" no afecta a "anthropikismo". El valor conserva su grafía,
    ajustando solo el case inicial según la palabra original.
    """
    if not replacements or not text:
        return text

    # Mapa en minúsculas -> reemplazo canónico.
    lookup = {k.lower(): v for k, v in replacements.items() if k}
    if not lookup:
        return text

    # Una sola pasada con alternancia de todas las claves (las más largas primero
    # para evitar solapamientos).
    keys = sorted(lookup, key=len, reverse=True)
    pattern = re.compile(
        r"\b(" + "|".join(re.escape(k) for k in keys) + r")\b",
        re.IGNORECASE | re.UNICODE,
    )

    def _sub(m: re.Match[str]) -> str:
        original = m.group(0)
        replacement = lookup[original.lower()]
        return _match_case(original, replacement)

    return pattern.sub(_sub, text)


def apply_fuzzy(
    text: str,
    terms: Iterable[str],
    *,
    threshold: int = 85,
) -> str:
    """Corrige palabras parecidas a algún término del diccionario por similitud.

    Requiere ``rapidfuzz``. Si no está instalado, devuelve el texto sin cambios.
    Útil para variantes fonéticas que las reglas exactas no capturan.
    """
    term_list = [t.strip() for t in terms if t and t.strip()]
    if not term_list or not text:
        return text
    try:
        from rapidfuzz import fuzz, process
    except ImportError:
        return text

    def _replace(m: re.Match[str]) -> str:
        word = m.group(0)
        # No tocar palabras que ya coinciden exactamente con un término.
        if word in term_list:
            return word
        match = process.extractOne(word, term_list, scorer=fuzz.ratio)
        if match and match[1] >= threshold and match[0].lower() != word.lower():
            return _match_case(word, match[0])
        return word

    return _WORD_RE.sub(_replace, text)


__all__ = ["build_prompt", "apply", "apply_fuzzy"]
