"""Minimaler .env-Loader (ohne Zusatz-Abhängigkeit).

Liest ``KEY=WERT``-Zeilen aus ``<repo>/.env`` und setzt sie als
Umgebungsvariablen – bereits gesetzte Werte werden nicht überschrieben
(echte Umgebungsvariablen haben also Vorrang, auch wenn sie leer sind).

Unterstützt Kommentare (``#``) und einfache/doppelte Anführungszeichen.
"""
from __future__ import annotations

import os
from pathlib import Path


def load(path: str | Path) -> list[str]:
    """Lädt die Datei und gibt die Namen der gesetzten Keys zurück."""
    p = Path(path)
    if not p.exists():
        return []
    applied: list[str] = []
    for raw in p.read_text(encoding="utf-8", errors="replace").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, val = line.partition("=")
        key = key.strip()
        val = val.strip()
        if len(val) >= 2 and val[0] == val[-1] and val[0] in "\"'":
            val = val[1:-1]
        # Vorrang hat, was die Umgebung explizit setzt – auch ein leerer Wert
        # (damit lässt sich der Demo-Modus bewusst erzwingen, z. B. OPENROUTER_API_KEY=).
        if not key or not val or key in os.environ:
            continue
        os.environ[key] = val
        applied.append(key)
    return applied
