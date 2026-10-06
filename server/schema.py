"""Structured-Output-Schemata je Kachel (Plan Abschnitt 4.1).

Die Schemata sind bewusst **flach und klein** gehalten: das LLM extrahiert nur
Eingangsdaten und Kernaussagen. Alle Zahlen, die in einen Export gehen,
entstehen anschließend im Rechenkern (``server/calc.py``).

Je Kachel:
  * ``SCHEMAS[tile_id]``  → JSON-Schema für ``response_format``
  * ``FELDER[tile_id]``   → Kurzbeschreibung, was das Modell liefern soll
"""
from __future__ import annotations

from typing import Any

_GENERIC: dict[str, Any] = {
    "type": "object",
    "properties": {
        "zusammenfassung": {"type": "string", "description": "3–5 Sätze Kernergebnis."},
        "kernaussagen": {"type": "array", "items": {"type": "string"}, "description": "Prüfbare Aussagen."},
        "annahmen": {"type": "array", "items": {"type": "string"},
                     "description": "Alle gesetzten Annahmen, je als eigener Eintrag."},
        "quellen": {"type": "array", "items": {"type": "string"},
                    "description": "Nur sichere Quellen; sonst 'Quelle prüfen' eintragen."},
        "naechste_schritte": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["zusammenfassung", "kernaussagen", "annahmen"],
    "additionalProperties": False,
}

_CO2: dict[str, Any] = {
    "type": "object",
    "properties": {
        "betrachtungsrahmen": {"type": "string"},
        "bilanzjahr": {"type": "string"},
        "gruppen": {
            "type": "array",
            "description": "Fahrzeug-/Verkehrsgruppen mit den Angaben der Kommune.",
            "items": {
                "type": "object",
                "properties": {
                    "bezeichnung": {"type": "string"},
                    "anzahl": {"type": "number"},
                    "km_jahr": {"type": "number", "description": "Jahresfahrleistung je Fahrzeug"},
                    "verbrauch_je_100km": {"type": "number", "description": "l bzw. kWh je 100 km"},
                    "kraftstoff": {"type": "string",
                                   "enum": ["diesel", "benzin", "erdgas", "hvo", "elektro", "oekostrom"]},
                    "fahrgaeste": {"type": "number", "description": "Ø Fahrgäste je Fahrzeug (optional)"},
                    "quelle": {"type": "string", "description": "Datei/Angabe, aus der die Werte stammen"},
                },
                "required": ["bezeichnung", "anzahl", "km_jahr", "kraftstoff"],
                "additionalProperties": False,
            },
        },
        "strommix_g_kwh": {"type": "number", "description": "Falls die Kommune einen Faktor vorgibt."},
        "well_to_tank": {"type": "boolean", "description": "Vorkette ausweisen?"},
        "annahmen": {"type": "array", "items": {"type": "string"}},
        "datenluecken": {"type": "array", "items": {"type": "string"}},
        "einsparpotenziale": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "massnahme": {"type": "string"},
                    "wirkung": {"type": "string"},
                    "aufwand": {"type": "string"},
                    "prioritaet": {"type": "string", "enum": ["hoch", "mittel", "niedrig"]},
                },
                "required": ["massnahme", "wirkung"],
                "additionalProperties": False,
            },
        },
    },
    "required": ["betrachtungsrahmen", "bilanzjahr", "gruppen", "annahmen"],
    "additionalProperties": False,
}

_MASSNAHMEN: dict[str, Any] = {
    "type": "object",
    "properties": {
        "kontext": {"type": "string"},
        "massnahmen": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "name": {"type": "string"},
                    "beschreibung": {"type": "string"},
                    "wirkung": {"type": "number", "description": "1–5, 5 = sehr hohe Wirkung"},
                    "sicherheit": {"type": "number", "description": "1–5 Beitrag zur Verkehrssicherheit"},
                    "kosten": {"type": "number", "description": "1–5, 5 = sehr günstig"},
                    "aufwand": {"type": "number", "description": "1–5, 5 = sehr schnell umsetzbar"},
                    "akzeptanz": {"type": "number", "description": "1–5 politische Akzeptanz"},
                    "kosten_band": {"type": "string", "description": "z. B. '80–200 €/m' oder '350–500 k€'"},
                    "zeitrahmen": {"type": "string", "enum": ["sofort", "kurzfristig", "mittelfristig"]},
                    "kpi": {"type": "string"},
                },
                "required": ["name", "wirkung", "kosten", "aufwand", "zeitrahmen"],
                "additionalProperties": False,
            },
        },
        "annahmen": {"type": "array", "items": {"type": "string"}},
        "naechste_schritte": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["massnahmen", "annahmen"],
    "additionalProperties": False,
}

_OPNV: dict[str, Any] = {
    "type": "object",
    "properties": {
        "linie": {"type": "string"},
        "laenge_km": {"type": "number"},
        "geschwindigkeit_kmh": {"type": "number"},
        "haltestellen": {"type": "number"},
        "wendezeit_min": {"type": "number"},
        "takt_hvz_min": {"type": "number"},
        "takt_nvz_min": {"type": "number"},
        "betriebsstunden_tag": {"type": "number"},
        "kapazitaet": {"type": "number"},
        "fahrgaeste_tag": {"type": "number"},
        "abschnitte": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "abschnitt": {"type": "string"},
                    "takt_hvz_min": {"type": "number"},
                    "takt_nvz_min": {"type": "number"},
                    "anmerkung": {"type": "string"},
                },
                "required": ["abschnitt"],
                "additionalProperties": False,
            },
        },
        "annahmen": {"type": "array", "items": {"type": "string"}},
        "risiken": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["linie", "laenge_km", "geschwindigkeit_kmh", "takt_hvz_min", "annahmen"],
    "additionalProperties": False,
}

_WEGE: dict[str, Any] = {
    "type": "object",
    "properties": {
        "trasse": {"type": "string"},
        "abschnitte": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "abschnitt": {"type": "string"},
                    "laenge_m": {"type": "number"},
                    "avs": {"type": "number", "description": "Kfz/24 h (Verkehrsbelastung)"},
                    "trennungsform": {"type": "string"},
                    "breite_m": {"type": "number"},
                    "kosten_min_eur_pro_m": {"type": "number"},
                    "kosten_max_eur_pro_m": {"type": "number"},
                    "hinweis": {"type": "string"},
                },
                "required": ["abschnitt", "laenge_m", "trennungsform"],
                "additionalProperties": False,
            },
        },
        "annahmen": {"type": "array", "items": {"type": "string"}},
        "naechste_schritte": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["abschnitte", "annahmen"],
    "additionalProperties": False,
}

SCHEMAS: dict[str, dict[str, Any]] = {
    "co2-bilanz": _CO2,
    "massnahmenplanung": _MASSNAHMEN,
    "opnv-planung": _OPNV,
    "wegeplanung": _WEGE,
}

FELDER: dict[str, str] = {
    "co2-bilanz": "Fahrzeug-/Verkehrsgruppen mit Anzahl, Jahresfahrleistung, Verbrauch und Kraftstoffart "
                  "sowie Einsparpotenziale. Rechne die Emissionen NICHT selbst aus.",
    "massnahmenplanung": "Maßnahmenkatalog mit Bewertung 1–5 (Wirkung, Sicherheit, Kosten, Aufwand, Akzeptanz), "
                         "Kostenband, Zeitrahmen und KPI. Keine Gesamtsummen bilden.",
    "opnv-planung": "Linienparameter (Länge, Geschwindigkeit, Haltestellen, Wendezeit, Takte, Kapazität, "
                    "Fahrgäste) und Abschnittstakte. Umlaufzeit/Fahrzeugbedarf NICHT selbst rechnen.",
    "wegeplanung": "Trassenabschnitte mit Länge, Verkehrsbelastung, Trennungsform, Breite und Kostenband. "
                   "Kosten NICHT selbst summieren.",
}

RECHEN_HINWEIS = (
    "## Rechenregel (verbindlich)\n"
    "Zahlen werden von SusMob im Code berechnet – nicht von dir. Liefere ausschließlich die "
    "Eingangsdaten (Zahlen mit Einheit) und benenne jede Annahme. Wenn du eine Größe nicht aus den "
    "Angaben ableiten kannst, lass sie weg oder markiere sie als Annahme. Erfinde keine Messwerte, "
    "Fördersätze oder Fristen."
)
