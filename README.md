# 🚌 SusMob

Kommunale Kachel-App für **Mobilitätsmanagement & nachhaltige Mobilität**.
Jede Kachel = eine Aufgabenstellung (CO₂-Bilanz, Beschlussvorlagen, ÖPNV-Planung, …).
Die Kommune lädt Material hoch, chatted mit dem Fach-Bot (via **OpenRouter**, Modell je Kachel wählbar),
erhält Rückfragen und am Ende ein strukturiertes Ergebnis.

## Kacheln

| Kachel | Modell (Default) |
|---|---|
| 🌍 CO₂-Bilanz | `anthropic/claude-sonnet-4` |
| 📄 Beschlussvorlagen & Förderanträge | `anthropic/claude-sonnet-4` |
| 🎯 Klimaschutzkonzept | `anthropic/claude-sonnet-4` |
| 🧭 Maßnahmenplanung Mobilität | `anthropic/claude-sonnet-4` |
| 🚲 Wegeplanung Fahrrad | `anthropic/claude-sonnet-4` |
| 🗣️ Argumentationshilfe intern | `google/gemini-2.5-flash` |
| 🚌 ÖPNV-Planung | `anthropic/claude-sonnet-4` |

Neue Kacheln: Eintrag in `server/seed.py` (`TILES`, `PROMPTS`, optional `STANDARDWERTE`, `SUGGESTIONS`, `TESTFAELLE`) + Server-Neustart (Seed läuft nur bei leerer DB).

## Quickstart

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
export OPENROUTER_API_KEY="sk-or-..."          # Pflicht für echte Chat-Antworten
# export ADMIN_PASSWORD="geheim"               # optional: schützt den Admin-Bereich
.venv/bin/python -m uvicorn server.main:app --host 0.0.0.0 --port 8080
```

- App: `http://localhost:8080/`
- Admin (System-Prompts): `http://localhost:8080/#/admin`
- Ohne `OPENROUTER_API_KEY` läuft die App im Demo-Modus (UI/Upload/Standardwerte funktionieren, Chat antwortet mit Hinweis).

## Architektur

```
index.html + static/      → schlanke SPA (vanilla JS, Hash-Router, SSE-Streaming, Mini-Markdown)
server/main.py            → FastAPI: Tiles, Konversationen, Upload, Chat-Stream, Admin-API
server/seed.py            → Kacheln, Fach-System-Prompts, Standardwerte, Testfälle (Seed)
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
GET  /api/models                         Modell-Liste für Admin-Dropdown
POST /api/conversations                  {tile_id}
GET  /api/conversations?tile_id=...
GET  /api/conversations/{id}             + messages + files
DELETE /api/conversations/{id}
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
```

## Roadmap / Ideen

- [ ] Multi-Tenancy / Benutzerauth (Profil je Kommune, getrennte Daten)
- [ ] Ergebnis-Export (PDF/DOCX) für Beschlussvorlagen
- [ ] Embeddings-/Vektorsuche für große Datendokumente statt Bruchkürzung
- [ ] Diagramme (Bilanz-Donut, Takt-Tafel) client-seitig aus strukturierten Antworten
- [ ] Audit-Log aller LLM-Calls (Modell, Tokens, Kosten)
