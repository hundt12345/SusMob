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
| 📄 Beschlussvorlagen & Förderanträge | Beschlussvorlage E-Bus-Erwerb | `qwen/qwen3.8-27b:free` |
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
OPENROUTER_API_KEY="sk-or-..."   # Pflicht für echte Chat-Antworten
ADMIN_PASSWORD="geheim"          # optional: schützt den Admin-Bereich
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
GET  /api/admin/examples                 Status der Beispiele je Kachel
POST /api/admin/examples/regenerate      [?tile_id=...] Beispiele mit echtem Modell neu erzeugen
```

## Betrieb ohne Internetzugang (Sandbox/Vorschau)

Der Chat braucht eine ausgehende Verbindung zu `openrouter.ai`. Ist sie gesperrt (z. B. in
abgeschotteten Vorschau-Umgebungen), antwortet der Chat mit einem klaren Hinweis statt mit einem
Modellergebnis – **Beispiele, Oberfläche, Upload, Standardwerte und Admin funktionieren trotzdem**
vollständig, weil die Beispiele als statische Verläufe in der Datenbank liegen.

## Roadmap / Ideen

- [ ] Multi-Tenancy / Benutzerauth (Profil je Kommune, getrennte Daten)
- [ ] Ergebnis-Export (PDF/DOCX) für Beschlussvorlagen
- [ ] Embeddings-/Vektorsuche für große Datendokumente statt Bruchkürzung
- [ ] Diagramme (Bilanz-Donut, Takt-Tafel) client-seitig aus strukturierten Antworten
- [ ] Audit-Log aller LLM-Calls (Modell, Tokens, Kosten)
