# 🚌 SusMob

Kommunale Kachel-App für **Mobilitätsmanagement & nachhaltige Mobilität**.
Jede Kachel = eine Aufgabenstellung (CO₂-Bilanz, Beschlussvorlagen, ÖPNV-Planung, …).
Die Kommune lädt Material hoch, chatted mit dem Fach-Bot (via **OpenRouter**, Modell je Kachel
wählbar), erhält Rückfragen und am Ende ein **prüfbares Ergebnisdokument mit Export**
(Excel, CSV, JSON, Markdown, Diagramme, PDF/Druck) und – wo sinnvoll – **berechnete Zahlen
aus einem Python-Rechenkern** statt aus dem Sprachmodell.

Der Umsetzungsstand des zugehörigen Plans steht in [`plan.md`](plan.md);
die Anleitung für eine öffentlich erreichbare Test-Homepage in
[`docs/TESTHOMEPAGE.md`](docs/TESTHOMEPAGE.md).

## Kacheln (10)

Alle Kacheln laufen per Default auf **Gratis-Modellen** (OpenRouter, `:free`) und haben eine
**Fallback-Kette von drei Modellen**: Fällt ein Anbieter aus (429, 5xx, kein aktiver Endpunkt),
versucht die App automatisch das nächste Modell. Free-Tier-Limits: ca. 20 Requests/Minute und
50/Tag (1.000/Tag ab einmalig 10 $ Guthaben).

| Kachel | Modell (Default, gratis) | Fallbacks | Rechenkern |
|---|---|---|---|
| 🌍 CO₂-Bilanz | `nvidia/nemotron-3-ultra-550b-a55b:free` | Nemotron Super, Gemma 4 31B | ✅ Fuhrpark-Bilanz mit Emissionsfaktoren |
| 📄 Beschlussvorlagen & Förderanträge | `apodex/apodex-1.1-mini:free` | Nemotron Super, Gemma 4 31B | ✅ TCO Diesel vs. Elektro |
| 🎯 Klimaschutzkonzept | `thinkingmachines/inkling:free` | Nemotron Ultra, Nemotron Super | – |
| 🧭 Maßnahmenplanung Mobilität | `google/gemma-4-26b-a4b-it:free` | Inkling, Nemotron Super | – |
| 🚲 Wegeplanung Fahrrad | `google/gemma-4-31b-it:free` | Nemotron Super, Inkling | ✅ Kostenband & Budgetdeckung |
| 🗣️ Argumentationshilfe intern | `nvidia/nemotron-3.5-lightning:free` | Gemma 4 26B, Nemotron Super | ✅ TCO-Zahlen |
| 🚌 ÖPNV-Planung | `nvidia/nemotron-3-super-120b-a12b:free` | Apodex, Gemma 4 31B | ✅ Umlaufzeit, Fahrzeugbedarf, Taktstufen |
| 🚸 Verkehrssicherheit & Schulweg | `google/gemma-4-31b-it:free` | Nemotron Super, Lightning | ✅ Unfall-CSV → Gefahrenstellen-Ranking |
| 🔌 Ladeinfrastruktur-Konzept | `nvidia/nemotron-3-super-120b-a12b:free` | Gemma 4 26B, Apodex | ✅ Ladebedarf & Ausbaustufen |
| 🅿️ Parkraum & Bewirtschaftung | `nvidia/nemotron-3-super-120b-a12b:free` | Gemma 4 26B, Apodex | ✅ Bilanz, Überschuss, Amortisation |

Neue Kacheln: Eintrag in `server/seed.py` (`TILES`, `PROMPTS`, optional `STANDARDWERTE`,
`SUGGESTIONS`, `TESTFAELLE`) + Rechenkern in `server/rechner.py` + Schema in
`server/schemas.py`. Server-Neustart genügt – fehlende Kacheln werden automatisch ergänzt.

## Was die App kann

* **Chat mit Fach-Prompts**, Streaming (SSE), Rückfragen, Standardwerte je Kommune.
* **Fallback-Kette + Health-Check**: Prüft über die OpenRouter-Endpunktliste, ob ein Modell
  aktive Anbieter hat (genau der Qwen-Fall aus dem Plan) und weicht automatisch aus.
* **Ratenlimit-Behandlung**: 429/5xx mit `Retry-After` und exponentiellem Backoff.
* **Kostenmessung**: jeder Request landet in `llm_calls` (Tokens, Cache, Kosten, Dauer,
  Fallback, Fehler). Admin → „📈 Kosten, Health & Eval“ zeigt Kennzahlen je Kachel/Modell/Tag.
* **Audit-Log**: wer hat wann welches Ergebnis erzeugt, welche Datei hochgeladen, welcher
  Prompt geändert.
* **Rechnen im Code**: Zufuhr der berechneten Werte als verbindlicher Prompt-Abschnitt
  („Vorberechnete Werte … nicht nachrechnen“).
* **Ergebnisdokument**: JSON-Schema je Kachel, Pydantic-Validierung, ein Reparaturversuch,
  danach klarer Fehler statt Stillbruch.
* **Export**: Excel mit **Formeln auf das Annahmen-Blatt**, CSV, JSON, Markdown,
  SVG-Diagramme (Donut/Balken), Druck-HTML (A4) zum PDF-Speichern.
* **Bild-Input**: Fotos/Scans werden als multimodale Nachricht an Vision-Modelle gegeben
  (statt wie vorher verworfen).
* **Eval-Harness**: Testfälle laufen automatisch und werden nach Vollständigkeit, markierten
  Annahmen, **erfundenen Zahlen** und Format bewertet.
* **Datenschutz-Schalter**: `SUSMOB_MODE=produktion` + `SUSMOB_ALLOW_FREE_FOR_DATA=0` sperrt
  Gratis-Modelle für echte Daten.

## Quickstart

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
cp .env.example .env                           # OPENROUTER_API_KEY eintragen
.venv/bin/uvicorn server.main:app --host 0.0.0.0 --port 8080
```

* App: `http://localhost:8080/`
* Admin (Prompts, Modelle): `http://localhost:8080/#/admin`
* Admin (Kosten, Health, Audit, Eval): `http://localhost:8080/#/admin/system`
* Ohne `OPENROUTER_API_KEY` läuft die App im Demo-Modus: UI, Upload, Rechner, Export und
  Beispiele funktionieren; Chat antwortet mit Hinweis.

### Umgebungsvariablen (`.env`)

```bash
OPENROUTER_API_KEY="sk-or-..."          # Pflicht für echte Chat-Antworten
ADMIN_PASSWORD="geheim"                 # optional: schützt den Admin-Bereich
SUSMOB_MODE="demo"                      # demo | produktion
SUSMOB_ALLOW_FREE_FOR_DATA="1"          # 0 = Gratis-Modelle für Daten sperren
```

### Tests

```bash
.venv/bin/python -m pytest tests/ -q     # 38 Tests: Rechner, Schemas, Export, Eval, API
```

## Deploy / Test-Homepage

* **Docker**: `docker compose up -d app` (Volume `susmob-data` für DB/Uploads/Artefakte).
* **Mit Domain + TLS**: `DOMAIN=test.example.de docker compose --profile tls up -d`
  (Caddy holt Let's-Encrypt-Zertifikate, SSE wird nicht gepuffert).
* **Ohne Serverpflege**: `render.yaml` im Repo (Render.com); für Fly.io ein Volume auf
  `/app/data` mounten.
* **Schnellster Test**: `cloudflared tunnel --url http://localhost:8080`.

Details, Kosten und Stolperfallen: [`docs/TESTHOMEPAGE.md`](docs/TESTHOMEPAGE.md).

## Beispiel-Unterhaltungen („Beispiele ansehen“)

Jede Kachel bringt eine **fest gespeicherte Beispiel-Unterhaltung** mit (`server/examples.py`,
`server/examples_extra.py`), die den vollständigen Durchlauf zeigt – Rückfragen, Annahmen,
Tabellen, Ergebnis. Beispiele sind schreibgeschützt (`403`) und über
`POST /api/conversations/{id}/duplicate` als eigene Unterhaltung übernehmbar.
Neu erzeugen mit echtem Modell: Admin → Kachel → „🔁 Beispiel neu erzeugen“.

## Architektur

```
index.html + static/        → SPA (vanilla JS, Hash-Router, SSE, Mini-Markdown)
server/main.py              → FastAPI: Tiles, Konversationen, Upload, Chat, Ergebnis/Export, Admin
server/seed.py              → Kacheln, Prompts, Standardwerte, Testfälle, Migrationen
server/examples*.py         → Beispiel-Unterhaltungen je Kachel (schreibgeschützt)
server/llm.py               → OpenRouter-Client: Streaming, Fallback-Kette, Backoff, Usage
server/health.py            → Modell-Endpunkt-Health-Check, Kette, Modellfähigkeiten
server/telemetry.py         → llm_calls + audit_log + Kostenauswertung
server/rechner.py           → deterministische Rechenkerne je Kachel
server/schemas.py           → JSON-Schema + Pydantic-Validierung + Reparaturprompt
server/export.py            → Excel (Formeln), CSV, JSON, Markdown, SVG, Druck-HTML, Artefakte
server/eval.py              → Eval-Harness (Score, erfundene Zahlen, Vollständigkeit)
server/files.py             → Textextraktion + Bild-Erkennung (multimodal)
server/db.py                → SQLite (WAL) in data/susmob.db
data/                       → DB, Uploads, Artefakte (git-ignoriert)
```

## API (Auszug)

```
GET  /api/tiles                                  Kacheln (+hat_rechner, fallback_models)
GET  /api/models[?refresh=1]                     Modell-Liste (live, Gratis zuerst)
GET  /api/models/status                          Key? Live-Liste? Health-Zusammenfassung?
GET  /api/rechner                                alle Rechenkerne + Felder
GET  /api/tiles/{tid}/rechner                    Felder inkl. zuletzt gespeicherter Werte
POST /api/tiles/{tid}/rechner                    {values} → rechnet, speichert, protokolliert
GET  /api/tiles/{tid}/standardwerte              inkl. aktueller Nutzerwerte
PUT  /api/tiles/{tid}/standardwerte              {values: {key: val}}
POST /api/conversations/{id}/chat                SSE: token | retry | meta | error | done
POST /api/conversations/{id}/ergebnis            Structured Output + Validierung + Artefakte
GET  /api/conversations/{id}/ergebnis            gespeichertes Ergebnisdokument (+Markdown)
POST /api/conversations/{id}/export?format=…     xlsx | csv | json | md | html (Druck/PDF)
GET  /api/artifacts/{aid}/download|anzeige       Artefakt herunterladen / anzeigen
GET  /api/admin/metrics?days=30                  Kosten, Tokens, Fehler, KPIs
GET  /api/admin/health · POST /api/admin/health/check   Modell-Endpunkte prüfen
GET  /api/admin/audit                            Audit-Log
GET  /api/admin/eval · POST /api/admin/eval/run  Eval-Harness
GET  /healthz                                    Betriebs-Check (Tiles, Key, letzter Call)
```

## Betrieb ohne Internetzugang (Sandbox/Vorschau)

Der Chat braucht eine ausgehende Verbindung zu `openrouter.ai`. Ist sie gesperrt (z. B. in
abgeschotteten Vorschau-Umgebungen), antwortet der Chat mit klarer Meldung – **Beispiele,
Oberfläche, Upload, Rechner, Ergebnis/Export und Admin funktionieren trotzdem** vollständig.
Im Admin → „📈 Kosten, Health & Eval“ zeigt der Health-Check die Netzsperre an.

## Roadmap / Ideen

* [ ] Multi-Tenancy / Benutzerauth (Kommune = Mandant, Rollen, Datenisolation) – Phase 4
* [ ] PDF mit Briefkopf-Vorlage (WeasyPrint) für Beschlussvorlagen
* [ ] Förderdatenbank + Fristenkalender (Kachel 9)
* [ ] Weitere Kacheln: Modal-Split-Monitoring, Verkehrsversuch, On-Demand, City-Logistik
* [ ] Embeddings-/Vektorsuche für große Datendokumente
* [ ] Kostenoptimierung: Prompt-Kürzung mit Eval-Nachweis, Modell-Routing, Caching bei Paid
