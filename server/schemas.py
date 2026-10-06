"""Structured-Output-Schemas je Kachel (Phase 1 des Plans).

Markdown ist gut fürs Auge, aber unbrauchbar für Dateien. Deshalb bekommt jede
Kachel ein JSON-Schema (``result_schema``), das das Modell über
``response_format={"type": "json_schema", …}`` erzeugen muss. Anschließend wird
mit Pydantic validiert; bei Schemafehlern folgt **ein** Reparaturversuch mit
Fehlermeldung, danach greift der Text-Fallback (nie ein Stillbruch).

Die validierten Daten sind die Grundlage für Excel, CSV, SVG-Diagramme und PDF.
"""
from __future__ import annotations

from typing import Any, Literal, Optional

from pydantic import BaseModel, Field, ValidationError

# ------------------------------------------------------------------ Bausteine


class Massnahme(BaseModel):
    name: str
    handlungsfeld: str = ""
    kosten_eur: float = 0
    kosten_band: str = ""
    wirkung: str = ""
    kpi: str = ""
    phase: str = ""
    traeger: str = ""
    foerderung: str = ""
    prioritaet: str = ""
    quelle: str = ""


class Kennzahl(BaseModel):
    bezeichnung: str
    wert: str
    einheit: str = ""
    quelle: str = ""


class Annahme(BaseModel):
    text: str
    quelle: str = ""
    pruefen: bool = True


class Phase(BaseModel):
    name: str
    zeitraum: str = ""
    inhalt: str = ""
    kosten_eur: float = 0


class Abschnitt(BaseModel):
    name: str
    laenge_m: float = 0
    standard: str = ""
    trennung: str = ""
    kosten_min_eur: float = 0
    kosten_max_eur: float = 0


class ErgebnisBasis(BaseModel):
    titel: str
    zusammenfassung: str = ""
    eingaben: dict[str, Any] = Field(default_factory=dict)  # Angaben der Kommune (Eingangsdaten-Blatt)
    annahmen: list[str] = Field(default_factory=list)
    quellen: list[str] = Field(default_factory=list)
    naechste_schritte: list[str] = Field(default_factory=list)
    hinweis_quellenpruefung: str = "Förder-/Rechtsangaben sind Annahmen und vor Verwendung zu prüfen."


# ------------------------------------------------------------------ Kachel-Schemas


class Co2Zeile(BaseModel):
    verkehrstraeger: str
    fahrleistung_km_jahr: float = 0
    energieverbrauch: float = 0
    energie_einheit: str = ""
    emissionsfaktor: str = ""
    co2_t_jahr: float = 0
    anteil_prozent: float = 0
    quelle: str = ""


class Co2Ergebnis(ErgebnisBasis):
    basisjahr: str = ""
    bilanz: list[Co2Zeile] = Field(default_factory=list)
    summe_t_co2_jahr: float = 0
    einsparpotenziale: list[Massnahme] = Field(default_factory=list)


class BeschlussErgebnis(ErgebnisBasis):
    betreff: str = ""
    vorlagen_nr: str = ""
    gremium: str = ""
    kommune: str = ""
    sachstand: str = ""
    beschlussvorschlag: str = ""
    finanzplan: dict[str, Any] = Field(default_factory=dict)
    anlagen: list[str] = Field(default_factory=list)
    pruefliste: list[str] = Field(default_factory=list)
    foerderprogramme: list[dict[str, Any]] = Field(default_factory=list)


class OepnvErgebnis(ErgebnisBasis):
    linie: str = ""
    umlaufzeit_min: float = 0
    fahrzeugbedarf: int = 0
    fahrleistung_km_jahr: float = 0
    kosten_jahr_eur: float = 0
    kosten_je_fahrgast_eur: float = 0
    takt: list[dict[str, Any]] = Field(default_factory=list)
    massnahmen: list[Massnahme] = Field(default_factory=list)


class MassnahmenErgebnis(ErgebnisBasis):
    massnahmen: list[Massnahme] = Field(default_factory=list)
    phasen: list[Phase] = Field(default_factory=list)
    kpis: list[Kennzahl] = Field(default_factory=list)


class WegeErgebnis(ErgebnisBasis):
    abschnitte: list[Abschnitt] = Field(default_factory=list)
    kosten_min_eur: float = 0
    kosten_max_eur: float = 0
    foerderung: str = ""
    bauablauf: list[str] = Field(default_factory=list)
    konflikte: list[str] = Field(default_factory=list)


class ArgumentErgebnis(ErgebnisBasis):
    argumente: list[dict[str, Any]] = Field(default_factory=list)
    kennzahlen: list[Kennzahl] = Field(default_factory=list)
    gegenargumente: list[dict[str, Any]] = Field(default_factory=list)


class SicherheitErgebnis(ErgebnisBasis):
    ranking: list[dict[str, Any]] = Field(default_factory=list)
    massnahmen: list[Massnahme] = Field(default_factory=list)
    zustaendigkeiten: list[str] = Field(default_factory=list)


class LadeErgebnis(ErgebnisBasis):
    bedarf_heute: dict[str, Any] = Field(default_factory=dict)
    bedarf_zielbild: dict[str, Any] = Field(default_factory=dict)
    ausbaustufen: list[Phase] = Field(default_factory=list)
    standortkriterien: list[str] = Field(default_factory=list)
    foerderprogramme: list[dict[str, Any]] = Field(default_factory=list)


class ParkraumErgebnis(ErgebnisBasis):
    bilanz: dict[str, Any] = Field(default_factory=dict)
    bewirtschaftung: dict[str, Any] = Field(default_factory=dict)
    massnahmen: list[Massnahme] = Field(default_factory=list)


class AllgemeinErgebnis(ErgebnisBasis):
    kennzahlen: list[Kennzahl] = Field(default_factory=list)
    massnahmen: list[Massnahme] = Field(default_factory=list)
    bilanz: list[dict[str, Any]] = Field(default_factory=list)
    offene_fragen: list[str] = Field(default_factory=list)


SCHEMAS: dict[str, type[BaseModel]] = {
    "co2-bilanz": Co2Ergebnis,
    "beschlussvorlagen": BeschlussErgebnis,
    "klimaschutzkonzept": MassnahmenErgebnis,
    "massnahmenplanung": MassnahmenErgebnis,
    "wegeplanung": WegeErgebnis,
    "argumentation": ArgumentErgebnis,
    "opnv-planung": OepnvErgebnis,
    "verkehrssicherheit": SicherheitErgebnis,
    "ladeinfrastruktur": LadeErgebnis,
    "parkraum": ParkraumErgebnis,
}

# Zusatzhinweise je Kachel für den Extraktionsauftrag
EXTRAKTION: dict[str, str] = {
    "co2-bilanz": "Fülle `bilanz` mit einer Zeile je Verkehrsträger und `summe_t_co2_jahr`. Übernimm die Zahlen des Rechenkerns, wenn welche vorliegen.",
    "beschlussvorlagen": "Fülle `beschlussvorschlag` im Konjunktiv I, `finanzplan` mit Investition/Folgekosten/Finanzierung und `pruefliste`.",
    "klimaschutzkonzept": "`massnahmen` = Maßnahmen je Sektor mit Wirkung, `phasen` = Umsetzungsphasen, `kpis` = Monitoring-Indikatoren.",
    "massnahmenplanung": "`massnahmen` = priorisierter Katalog, `phasen` = Zeitplan, `kpis` = Wirkungsindikatoren.",
    "wegeplanung": "`abschnitte` = Streckenabschnitte mit Standard/Trennung und Kostenband, `konflikte` = offene Punkte.",
    "argumentation": "`argumente` = Liste {argument, beleg, quelle}, `gegenargumente` = Liste {einwand, entkraeftung}, `kennzahlen` = belastbare Zahlen.",
    "opnv-planung": "`takt` = Liste {takt_min, fahrzeuge, fahrten_tag, kosten_jahr_eur}, `massnahmen` = nötige Schritte.",
    "verkehrssicherheit": "`ranking` = Liste {ort, unfaelle, schwere_unfaelle, verletzte, punkte, kategorie}, `massnahmen` = Maßnahmen je Stelle.",
    "ladeinfrastruktur": "`bedarf_heute`/`bedarf_zielbild` = {e_pkw, ladepunkte_ac, ladepunkte_dc, ladepunkte_gesamt, investition_eur}.",
    "parkraum": "`bilanz` = {parkstaende, auslastung_prozent, freie_parkstaende}, `bewirtschaftung` = {einnahmen, kosten, ueberschuss}.",
}


def model_for(tile_id: str) -> type[BaseModel]:
    return SCHEMAS.get(tile_id, AllgemeinErgebnis)


def schema_for(tile_id: str) -> dict:
    model = model_for(tile_id)
    schema = model.model_json_schema()
    schema["additionalProperties"] = False
    return schema


# ------------------------------------------------------------------ JSON-Werkzeuge


def extract_json(text: str) -> dict | None:
    """Zieht das erste JSON-Objekt aus einer Antwort (auch mit ```-Zaun oder Vorrede)."""
    if not text:
        return None
    t = text.strip()
    if t.startswith("```"):
        t = t.split("```")[1] if len(t.split("```")) > 1 else t
        if t.lstrip().lower().startswith("json"):
            t = t.lstrip()[4:]
    t = t.strip()
    start = t.find("{")
    end = t.rfind("}")
    if start < 0 or end <= start:
        return None
    try:
        import json

        return json.loads(t[start:end + 1])
    except Exception:  # noqa: BLE001 – häufigster Fall: Prosa um das JSON
        try:
            import json

            decoder = json.JSONDecoder()
            obj, _ = decoder.raw_decode(t[start:])
            return obj if isinstance(obj, dict) else None
        except Exception:  # noqa: BLE001
            return None


def validate(tile_id: str, payload: dict | None) -> tuple[BaseModel | None, list[str]]:
    """Validiert gegen das Kachel-Schema. Rückgabe: (Objekt, Fehlerliste)."""
    if payload is None:
        return None, ["Kein JSON-Objekt in der Antwort gefunden."]
    model = model_for(tile_id)
    try:
        obj = model.model_validate(payload)
    except ValidationError as e:
        errors = []
        for err in e.errors()[:8]:
            loc = ".".join(str(p) for p in err.get("loc", ()))
            errors.append(f"{loc}: {err.get('msg')}")
        return None, errors or ["Schemaverletzung"]
    return obj, []


def repair_messages(tile_id: str, original_messages: list[dict], raw_answer: str, errors: list[str]) -> list[dict]:
    """Reparaturprompt: das Modell bekommt Schemaverletzung + Zielschema und antwortet erneut."""
    import json

    hint = EXTRAKTION.get(tile_id, "")
    schema_hint = json.dumps(schema_for(tile_id), ensure_ascii=False)[:4000]
    return [
        original_messages[0],
        *original_messages[1:],
        {"role": "assistant", "content": raw_answer[:4000]},
        {
            "role": "user",
            "content": (
                "Deine JSON-Ausgabe war nicht schema-konform.\n\n"
                f"Fehler:\n- " + "\n- ".join(errors[:8]) + "\n\n"
                f"Zielschema (JSON Schema):\n{schema_hint}\n\n"
                f"{hint}\n\n"
                "Antworte **ausschließlich** mit einem korrigierten JSON-Objekt nach diesem Schema. "
                "Keine Erklärungen, keine Code-Zäune, keine zusätzlichen Felder."
            ),
        },
    ]


def extraktion_messages(tile_id: str, system_prompt: str, kontext: str, frage: str) -> list[dict]:
    """Baut den strukturierten Extraktionsauftrag (LLM → JSON)."""
    hint = EXTRAKTION.get(tile_id, "")
    return [
        {"role": "system", "content": system_prompt},
        {
            "role": "user",
            "content": (
                "Erstelle aus dem folgenden Gesprächsstand das **Ergebnisdokument als JSON** nach dem "
                "vorgegebenen Schema. Zahlen aus dem Rechenkern sind verbindlich zu übernehmen. "
                "Fehlende Angaben bleiben leer – nichts erfinden.\n\n"
                f"{hint}\n\n"
                f"## Gesprächsstand\n{kontext[:24000]}\n\n"
                f"## Auftrag\n{frage}\n\n"
                "Antworte ausschließlich mit dem JSON-Objekt."
            ),
        },
    ]


# ------------------------------------------------------------------ Rendering


def _zeilen(titel: str, spalten: list[str], rows: list[dict], keys: list[str] | None = None) -> str:
    keys = keys or spalten
    head = "| " + " | ".join(spalten) + " |\n|" + "|".join(["---"] * len(spalten)) + "|"
    body = []
    for r in rows:
        body.append("| " + " | ".join(str(r.get(k, "") if r.get(k) is not None else "") for k in keys) + " |")
    return (f"**{titel}**\n\n" if titel else "") + head + "\n" + "\n".join(body)


def to_markdown(tile_id: str, data: dict) -> str:
    """Rendert das validierte Ergebnis als Markdown (für Chat/PDF)."""
    model = model_for(tile_id)
    obj = model.model_validate(data) if not isinstance(data, model) else data
    d = obj.model_dump()
    out: list[str] = [f"# {d.get('titel') or 'Ergebnis'}"]
    if d.get("zusammenfassung"):
        out.append(str(d["zusammenfassung"]))
    for key, label, keys in (
        ("anlagen", "Anlagenverzeichnis", None),
        ("pruefliste", "Prüfliste vor Einreichung", None),
    ):
        if d.get(key):
            out.append(f"**{label}**\n" + "\n".join(f"- {x}" for x in d[key]))

    if d.get("bilanz"):
        bilanz = d["bilanz"]
        if isinstance(bilanz[0], dict) and "verkehrstraeger" in bilanz[0]:
            cols = ["verkehrstraeger", "fahrleistung_km_jahr", "energieverbrauch", "energie_einheit",
                    "co2_t_jahr", "anteil_prozent"]
            names = ["Verkehrsträger", "Fahrleistung [km/a]", "Energie", "Einheit", "t CO₂/a", "Anteil [%]"]
        elif isinstance(bilanz[0], dict):
            cols = list(bilanz[0].keys())[:6]
            names = [c.replace("_", " ") for c in cols]
        else:
            cols, names = [], []
        if cols:
            out.append(_zeilen("Bilanz", names, bilanz, cols))
        if d.get("summe_t_co2_jahr"):
            out.append(f"**Summe: {d['summe_t_co2_jahr']} t CO₂/a**")

    for key, titel, spalten, keys in (
        ("massnahmen", "Maßnahmen", ["Maßnahme", "Handlungsfeld", "Kosten [€]", "Wirkung", "KPI", "Phase", "Priorität"],
         ["name", "handlungsfeld", "kosten_eur", "wirkung", "kpi", "phase", "prioritaet"]),
        ("einsparpotenziale", "Einsparpotenziale", ["Maßnahme", "Wirkung", "Aufwand", "Priorität"],
         ["name", "wirkung", "kosten_band", "prioritaet"]),
        ("kpis", "Kennzahlen", ["Bezeichnung", "Wert", "Einheit", "Quelle"], ["bezeichnung", "wert", "einheit", "quelle"]),
        ("kennzahlen", "Kennzahlen", ["Bezeichnung", "Wert", "Einheit", "Quelle"], ["bezeichnung", "wert", "einheit", "quelle"]),
        ("phasen", "Phasen", ["Phase", "Zeitraum", "Inhalt", "Kosten [€]"], ["name", "zeitraum", "inhalt", "kosten_eur"]),
        ("abschnitte", "Abschnitte", ["Abschnitt", "Länge [m]", "Standard", "Trennung", "Kosten von [€]", "Kosten bis [€]"],
         ["name", "laenge_m", "standard", "trennung", "kosten_min_eur", "kosten_max_eur"]),
        ("argumente", "Argumente", ["Argument", "Beleg", "Quelle"], ["argument", "beleg"]),
        ("gegenargumente", "Gegenargumente", ["Einwand", "Entkräftung", "Quelle"], ["einwand", "entkraeftung", "quelle"]),
        ("ranking", "Gefahrenstellen", ["Ort", "Unfälle", "davon schwer", "Verletzte", "Punkte", "Kategorie"],
         ["ort", "unfaelle", "schwere_unfaelle", "verletzte", "punkte", "kategorie"]),
        ("ausbaustufen", "Ausbaustufen", ["Stufe", "Zeit", "Maßnahme", "Kosten [€]"], ["name", "zeitraum", "inhalt", "kosten_eur"]),
    ):
        rows = d.get(key) or []
        if rows and isinstance(rows[0], dict):
            out.append(_zeilen(titel, spalten, rows, keys))

    for key, label in (
        ("beschlussvorschlag", "Beschlussvorschlag"),
        ("sachstand", "Sachstand"),
        ("finanzplan", "Finanzplan"),
        ("foerderung", "Förderung"),
        ("foerderhinweis", "Förderhinweis"),
        ("bewirtschaftung", "Bewirtschaftung"),
    ):
        if d.get(key):
            v = d[key]
            if isinstance(v, dict):
                out.append(f"**{label}**\n" + "\n".join(f"- {k.replace('_', ' ')}: {val}" for k, val in v.items()))
            else:
                out.append(f"**{label}**\n\n{v}")

    if d.get("annahmen"):
        out.append("**Annahmen**\n" + "\n".join(f"- {a}" for a in d["annahmen"]))
    if d.get("naechste_schritte"):
        out.append("**Nächste Schritte**\n" + "\n".join(f"- {s}" for s in d["naechste_schritte"]))
    if d.get("quellen"):
        out.append("**Quellen**\n" + "\n".join(f"- {q}" for q in d["quellen"]))
    if d.get("hinweis_quellenpruefung"):
        out.append(f"> ⚠️ {d['hinweis_quellenpruefung']}")
    return "\n\n".join(str(o) for o in out if o)


def flat_rows(tile_id: str, data: dict) -> dict[str, list[dict]]:
    """Tabellen für Excel/CSV: Blattname → Zeilen (konsistente Spalten je Block)."""
    model = model_for(tile_id)
    obj = model.model_validate(data) if not isinstance(data, model) else data
    d = obj.model_dump()
    out: dict[str, list[dict]] = {}
    if d.get("bilanz") and isinstance(d["bilanz"][0], dict):
        out["Bilanz"] = [dict(r) for r in d["bilanz"]]
    for key, name in (("massnahmen", "Massnahmen"), ("einsparpotenziale", "Massnahmen"),
                      ("phasen", "Phasen"), ("abschnitte", "Abschnitte"),
                      ("kpis", "Kennzahlen"), ("kennzahlen", "Kennzahlen"),
                      ("ranking", "Gefahrenstellen"), ("ausbaustufen", "Ausbaustufen")):
        rows = d.get(key) or []
        if rows and isinstance(rows[0], dict):
            out.setdefault(name, []).extend([dict(r) for r in rows])
    if d.get("annahmen"):
        out["Annahmen"] = [{"annahme": a} for a in d["annahmen"]]
    if d.get("quellen"):
        out.setdefault("Annahmen", []).extend({"quelle": q} for q in d["quellen"])
    if d.get("naechste_schritte"):
        out["Naechste_Schritte"] = [{"schritt": s} for s in d["naechste_schritte"]]
    return out
