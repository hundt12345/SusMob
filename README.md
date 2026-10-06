# 🚌 SusMob

Kommunale Kachel-App für **Mobilitätsmanagement & nachhaltige Mobilität**.
Jede Kachel = eine Aufgabenstellung (CO₂-Bilanz, Beschlussvorlagen, ÖPNV-Planung, …).
Die Kommune lädt Material hoch, chatted mit dem Fach-Bot (via **OpenRouter**, Modell je Kachel wählbar),
erhält Rückfragen und am Ende ein strukturiertes Ergebnis.

## Kacheln

Alle Kacheln laufen per Default auf **Gratis-Modellen** (OpenRouter, `:free`). Die Liste im
Admin-Bereich wird live von OpenRouter geladen; eigene (auch kostenpflichtige) Modell-IDs
bleiben möglich. Free-Tier-Limits: ca. 20 Requests/Minute und 50/Tag (1.000/Tag ab 10 $ Guthaben).

| Kachel | Beispiel-Unterhaltung | Modell (Default, gratis) |
|---|---|---|
| 🌍 CO₂-Bilanz | Fuhrpark-Bilanz 2024 (mit CSV) | `nvidia/nemotron-3-ultra-550b-a55b:free` |
| 📄 Beschlussvorlagen & Förderanträge | Beschlussvorlage E-Bus-Erwerb | `apodex/apodex-1.1-mini:free` |
| 🎯 Klimaschutzkonzept | Kleinstadt 15.000 EW | `nvidia/nemotron-3-super-120b-a12b:free` |
| 🧭 Maßnahmenplanung Mobilität | Maßnahmenkatalog Mittelstadt | `thinkingmachines/inkling:free` |
| 🚲 Wegeplanung Fahrrad | Radtrasse Nord → Gesamtschule (mit CSV) | `google/gemma-4-31b-it:free` |
| 🗣️ Argumentationshilfe intern | Argumente zur E-Bus-Wirtschaftlichkeit | `nvidia/nemotron-3.5-lightning:free` |
| 🚌 ÖPNV-Planung | Landbus-Taktkonzept 12 km | `apodex/apodex-1.1-mini:free` |

Neue Kacheln: Eintrag in `server/seed.py` (`TILES`, `PROMPTS`, optional `STANDARDWERTE`, `SUGGESTIONS`, `TESTFAELLE`) + Server-Neustart (Seed läuft nur bei leerer DB).

Beim Start werden außerdem automatisch migriert: alte Default-Modelle → Gratis-Modelle
(nur wenn die Kachel noch auf dem alten Default stand) und sachliche Prompt-Korrekturen
(nur wenn der Prompt unverändert ist).

## Beispiel-Unterhaltungen („Beispiele ansehen“)

Jede Kachel bringt eine **fest gespeicherte Beispiel-Unterhaltung** mit (`server/examples.py`),
die den vollständigen Durchlauf zeigt – Rückfragen, Annahmen, Tabellen, Ergebnis:

- Aufruf über die Startseite („📘 Beispiel ansehen“) oder `#/tile/<kachel>/beispiel`.
- Beispiele sind **schreibgeschützt** (Chat/Löschen antworten mit 403) und in der Seitenleiste
  getrennt von eigenen Unterhaltungen gelistet.
- Button **„Als eigene Unterhaltung übernehmen“** kopiert Nachrichten + Dateien in eine
  bearbeitbare Unterhaltung (`POST /api/conversations/{id}/duplicate`).
- **Mit echtem Modell neu erzeugen:** Admin-Bereich → Kachel → „🔁 Beispiel neu erzeugen“
  (`POST /api/admin/examples/regenerate[?tile_id=...]`). Läuft gegen das aktuell konfigurierte
  Modell und dieselben Prompts/Dateien; ohne `tile_id` werden alle Beispiele neu erzeugt.
  Achtung Free-Tier-Limit (1 Request je Assistenten-Antwort).

## Neu: Betriebssicherheit, Messbarkeit und Export (Umsetzung des Plans)

Der Plan (`plan.md`, im Repo abgelegt mit Umsetzungsstand) ist in den Phasen 0–2 umgesetzt. Kurzfassung:

### Phase 0 – Betriebssicherheit & Messbarkeit
- **Token-/Kostenmessung**: jeder Modell-Aufruf landet mit Tokens, Kosten, Dauer, Status in
  `llm_calls`; fehlt die `usage`, wird über Zeichen/3,3 geschätzt und als „geschätzt" markiert.
  Admin → **💵 Kosten & Tokens** zeigt Summen je Kachel, Modell, Tag und Funktion.
- **Modell-Health-Check**: prüft live die Endpunktliste je Modell (der „Qwen-Fall") und cacht das
  Ergebnis in `model_health`; Admin → **🩺 Modell-Health** zeigt Endpunkte, Uptime, Kontext,
  Structured-Output/Bild-Fähigkeit und die **Fallback-Kette je Kachel** (im Admin änderbar).
- **Fallback-Kette + 429-Backoff**: Modelle werden in Reihenfolge probiert (Seed in
  `server/seed.py → FALLBACK_KETTEN`, pro Kachel überschreibbar). Ein Anbieterausfall ist damit
  für Nutzer nur ein Hinweis im Chat (`notice`-Event), kein Fehler.
- **Audit-Log** (`audit_log`): Chat, Prompt-Änderung, Modellwechsel, Artefakt, Limit – Admin → 🔍 Audit-Log.
- **Kostenbremse** (`server/limits.py`): `SUSMOB_DAILY_REQUEST_BUDGET`, `SUSMOB_CHAT_LIMIT_PER_HOUR`,
  `SUSMOB_MAX_MESSAGE_CHARS` und Datenschutz-Flag `SUSMOB_DEMO_ONLY` – wichtig für öffentliche Test-Links.
- Der tote Kachel-Default `qwen/qwen3.8-27b:free` (keine aktiven Endpunkte) wird beim Start
  automatisch auf `apodex/apodex-1.1-mini:free` migriert.

### Phase 1 – Ergebnis-Export
- **Structured Output je Kachel** (`server/schema.py`): JSON-Schema für Bilanz, Maßnahmen,
  ÖPNV-Parameter und Trassen; Modellwahl nutzt `json_schema`, sonst `json_object`, sonst
  JSON-Extraktion.
- **Rechenkern** (`server/calc.py`, Phase 2 vorweggenommen): Emissionen, Umlaufzeit/Fahrzeugbedarf,
  TCO-Vergleich, Kostenbänder, Nutzwertanalyse – reines Python, getestet, ohne LLM.
- **Excel-Export** (`POST /api/conversations/{id}/export/xlsx`): Blätter *Annahmen* (editierbare
  Faktoren, gelb), *Bilanz* (Spalten als **Formeln** mit `VLOOKUP` auf die Annahmen), *Maßnahmen*
  (Score als gewichtete Summe der Annahmen-Gewichte), *Kosten*, *Hinweise*, *Antworttext*, inkl.
  Excel-Diagrammen. Ändert die Kommune einen Faktor, rechnet das Blatt neu.
- **JSON-Export** für Maschinenweiterverarbeitung, **PDF über Druck-CSS** (🖨️ Druckansicht im Chat,
  A4, Briefkopf-Platzhalter, Serifenlos-Amtlook) und **Diagramme** clientseitig (Donut/Balken) aus
  dem Rechenergebnis.
- **Antworttext-Parser** (`server/parse.py`): fehlt Netz/Key, zieht SusMob die Zahlen deterministisch
  aus den Standardtabellen der Antwort – klar gekennzeichnet als „nicht im Rechenkern nachgerechnet".

### Phase 2 – Qualitätssicherung
- **Eval-Harness** (`server/eval.py`): Testfälle je Kachel laufen automatisch gegen das Modell und
  werden nach festem Schema bewertet (Antwort, Tiefe, benannte Annahmen, Zahlen mit Einheit,
  Struktur, Quellen-/Scheinpräzisions-Check) – Admin → 🧪 Eval, Historie in `eval_runs`.
- **Tests**: `tests/` mit 32 Tests für Rechenkern, Export, Parser, Limits und API.

### Hosting / Test-Homepage mit Live-Chat
Siehe **[docs/BETRIEB.md](docs/BETRIEB.md)** – Wege, Kosten und Checkliste (Cloudflare-Tunnel 0 €,
Render-Free-Plan, Hugging Face Spaces, Fly.io, Docker), inklusive der Grenzen der Arena-Vorschau.

## Quickstart

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
cp .env.example .env                           # OPENROUTER_API_KEY eintragen
.venv/bin/python -m uvicorn server.main:app --host 0.0.0.0 --port 8080
```

Die Datei `.env` im Projektordner wird beim Start automatisch geladen (eigener Mini-Loader in
`server/envfile.py`, keine Zusatz-Abhängigkeit). Echte Umgebungsvariablen haben Vorrang:

```bash
OPENROUTER_API_KEY="sk-or-..."       # Pflicht für echte Chat-Antworten
ADMIN_PASSWORD="geheim"              # optional: schützt den Admin-Bereich
SUSMOB_DATA_DIR="/pfad/volume"       # optional: SQLite/Uploads/Artefakte ablegen (Hosting)
SUSMOB_DEMO_ONLY="1"                 # optional: Datenschutz-Banner für nur-Demo-Daten
SUSMOB_DAILY_REQUEST_BUDGET="50"     # optional: Gratis-Tier schützen
SUSMOB_CHAT_LIMIT_PER_HOUR="8"       # optional: pro IP und Stunde
SUSMOB_MAX_MESSAGE_CHARS="8000"      # optional: Nachrichtenlänge
```

Tests (ohne Netz, mit pytest):

```bash
.venv/bin/pip install pytest
.venv/bin/python -m pytest tests -q
```

- App: `http://localhost:8080/`
- Admin (System-Prompts): `http://localhost:8080/#/admin`
- Ohne `OPENROUTER_API_KEY` läuft die App im Demo-Modus (UI/Upload/Standardwerte funktionieren, Chat antwortet mit Hinweis).

## Architektur

```
index.html + static/      → schlanke SPA (vanilla JS, Hash-Router, SSE-Streaming, Mini-Markdown)
server/main.py            → FastAPI: Tiles, Konversationen, Upload, Chat-Stream, Admin-API
server/seed.py            → Kacheln, Fach-System-Prompts, Standardwerte, Testfälle (Seed), Migrationen
server/examples.py        → Beispiel-Unterhaltungen je Kachel (schreibgeschützt, übernehmbar)
server/envfile.py         → lädt .env (OPENROUTER_API_KEY, ADMIN_PASSWORD)
server/llm.py             → OpenRouter-Client (streaming + Einmal-Call)
server/files.py           → Text-Extraktion: txt/md/csv/json, xlsx, docx, pdf (gekürzt auf 12k Zeichen/Datei)
server/db.py              → SQLite (WAL) in data/susmob.db
data/uploads/             → hochgeladene Dateien (git-ignoriert)
```

### Wie ein Chat-Request zustandekommt

`System-Prompt (Admin, pro Kachel)` + `## Konfiguration der Kommune` (Standardwerte: Nutzerwerte > Defaults)
+ `## Hochgeladene Dateien` (extrahierter Text, gekürzt) + `## Gesprächsregeln` (Rückfragen, Annahmen kennzeichnen)
+ Historie (letzte 30 Nachrichten) + aktuelle Nutzernachricht → OpenRouter (Streaming, SSE an Frontend).

### Standardwerte

- **Nutzer-setzbar** (Kommune, pro Kachel in der Kachelansicht unter „⚙️ Standardwerte"): fließen als „Konfiguration der Kommune" in jeden Prompt und haben Vorrang.
- **Fachwerte im System-Prompt** (z. B. Besetzungsgrade, Emissionsfaktoren, Kraftstoffwerte): stehen als Fallback im Prompt, gelten nur wenn die Kommune nichts anderes angibt – und werden vom Bot als Annahme benannt.

### Admin-Bereich (`#/admin`)

- Modell & Temperature pro Kachel (Modell-Liste = gängige OpenRouter-Modelle, eigene IDs möglich)
- System-Prompt-Editor mit **Versionshistorie** (jedes Speichern = neue Version, restaurierbar)
- **Testlauf**: Testfall auswahlbbar/anlegbar (Nachricht + simulierter Dateikontext), läuft gegen den aktuellen Prompt
- Schutz: `ADMIN_PASSWORD` als Env setzen → Login erforderlich (Token im localStorage)

## API (Auszug)

```
GET  /api/tiles                          Kacheln (+Vorschläge)
GET  /api/models[?refresh=1]             Modell-Liste (live von OpenRouter, Gratis-Modelle zuerst)
GET  /api/models/status                  Diagnose: Key gesetzt? Live-Liste geladen?
POST /api/conversations                  {tile_id}
GET  /api/conversations?tile_id=...      eigene zuerst, is_example markiert Beispiele
GET  /api/conversations/{id}             + messages + files
POST /api/conversations/{id}/duplicate    Beispiel/eigene Unterhaltung als Kopie übernehmen
DELETE /api/conversations/{id}            (Beispiele: 403)
POST /api/conversations/{id}/files       multipart-Upload
DELETE /api/conversations/{id}/files/{fid}
POST /api/conversations/{id}/chat        SSE: event token | error | done
GET  /api/tiles/{id}/standardwerte       inkl. aktueller Nutzerwerte
PUT  /api/tiles/{id}/standardwerte       {values: {key: val}}
POST /api/admin/login                    {password} (falls ADMIN_PASSWORD gesetzt)
GET  /api/admin/tiles                    inkl. System-Prompts
PUT  /api/admin/tiles/{id}               {model?, temperature?, system_prompt?}
GET  /api/admin/tiles/{id}/versions
POST /api/admin/tiles/{id}/versions/{vid}/restore
GET/POST/DELETE /api/admin/tiles/{id}/test-cases
POST /api/admin/tiles/{id}/test          {message, file_content} → Antwort
GET  /api/status                         Betriebsstatus: Demo-Flag, Limits, Key, Live-Liste
POST /api/calc/{tile_id}                 Rechenkern ohne LLM (deterministisch, z. B. CO₂-Bilanz)
GET  /api/tiles/{id}/schema              Structured-Output-Schema + Rechenkern-Info der Kachel
POST /api/conversations/{id}/auswertung  Schema-Extraktion + Rechenkern → strukturiertes Ergebnis
POST /api/conversations/{id}/export/xlsx Excel mit Formeln + Annahmen-Blatt (auch PDF-Weg über UI)
POST /api/conversations/{id}/export/json Maschinenlesbares Ergebnis
GET  /api/artifacts/{id}                 Artefakt herunterladen
DELETE /api/artifacts/{id}               Artefakt löschen
GET  /api/admin/usage?days=30            Token-/Kostenmessung je Kachel, Modell, Tag, Funktion
GET  /api/admin/health[?refresh=1]       Modell-Health + Fallback-Ketten je Kachel
GET  /api/admin/audit?limit=100          Audit-Log
POST /api/admin/eval/run                 Eval-Harness starten (Testfälle bewerten)
GET  /api/admin/eval/results             Eval-Historie
PUT  /api/admin/tiles/{id}               {model?, temperature?, system_prompt?, fallback_models?}
GET  /api/admin/examples                 Status der Beispiele je Kachel
POST /api/admin/examples/regenerate      [?tile_id=...] Beispiele mit echtem Modell neu erzeugen
```

## Betrieb ohne Internetzugang (Sandbox/Vorschau)

Der Chat braucht eine ausgehende Verbindung zu `openrouter.ai`. Ist sie gesperrt (z. B. in
abgeschotteten Vorschau-Umgebungen), antwortet der Chat mit einem klaren Hinweis statt mit einem
Modellergebnis – **Beispiele, Oberfläche, Upload, Standardwerte und Admin funktionieren trotzdem**
vollständig, weil die Beispiele als statische Verläufe in der Datenbank liegen.

## Roadmap / Ideen (Plan-Stand)

Umgesetzt: Token-/Kostenmessung, Audit-Log, Health-Check + Fallback-Kette, Fehlerbilder,
Structured Output, Artefakt-/Exportsystem (Excel mit Formeln, PDF via Druck-CSS, Diagramme),
Rechenkerne (CO₂, ÖPNV, TCO, Kostenband, Priorisierung), Eval-Harness, Limit-/Kostenbremse.

Offen:
- [ ] Phase 3: neue Kacheln (Verkehrssicherheit/Schulweg, Ladeinfrastruktur, Parkraum …)
- [ ] Phase 4: Multi-Tenancy, Rollen, Anbieter mit AVV, Löschkonzept, Betriebshandbuch
- [ ] PDF serverseitig mit echten Vorlagen (WeasyPrint: Briefkopf, Seitenzahlen, Anlagenverzeichnis)
- [ ] Bild-Input (Bestandsfotos/Luftbilder) an die Vision-Modelle – heute wird nur Text extrahiert
- [ ] Embeddings-/Vektorsuche für große Datendokumente statt Bruchkürzung
- [ ] Rolling Summary / Kontext-Diät für lange Chats (Plan Abschnitt 3.5)
