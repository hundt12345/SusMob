# SusMob online stellen – schnell und günstig (Test-Homepage mit Live-Chat)

Ziel: eine **im Internet aufrufbare Test-Seite** mit Live-Chat, die mit **Gratis-Modellen** läuft
und möglichst nichts kostet. Stand: 06.10.2026.

---

## 0. Drei Entscheidungen vorab

| Frage | Konsequenz |
|---|---|
| Sollen **fremde Besucher** chatten? | Ja → Tages-/Stundenlimit setzen (`SUSMOB_DAILY_REQUEST_BUDGET`, `SUSMOB_CHAT_LIMIT_PER_HOUR`) und `ADMIN_PASSWORD` setzen. |
| Gehen **echte Kommunaldaten** durch die Seite? | Nein → `SUSMOB_DEMO_ONLY=1` (Banner + Audit-Eintrag). Gratis-Provider dürfen Prompts zum Training nutzen. |
| Muss der **Verlauf erhalten** bleiben? | Ja → Hosting mit Volume/Dateisystem (Fly.io, eigener Server, Hugging Face mit Storage). Bei Render-Freeservices ist das Dateisystem flüchtig (außer kostenpflichtiger Disk). |

---

## 1. Überblick: Wege ins Netz

| Weg | Aufwand | Kosten | Live-Chat | Dauerhaftigkeit | Bewertung |
|---|---|---|---|---|---|
| **A. Eigener Rechner + Cloudflare Tunnel** | 5 Min | **0 €** | ✅ | solange PC läuft | **Empfehlung für schnelle Tests** – keine Kreditkarte, kein Sleep, volle SQLite-Persistenz |
| **B. Render (Free-Plan)** | 10 Min | 0 € (Sleep nach ~15 min) | ✅ | FS flüchtig, Disk kostet | beste „echte" URL ohne eigenen Rechner |
| **C. Hugging Face Spaces (Docker)** | 15 Min | 0 € | ✅ | Space schläft, Storage kostenpflichtig | gut für Demo mit Code-Repos |
| **D. Fly.io / Railway** | 20 Min | ~2–5 $/Monat | ✅ | Volume verfügbar | beste Zuverlässigkeit im Kleinformat |
| **E. Vercel/Netlify** | – | 0 € | ⚠️ | – | **ungeeignet**: keine dauerhafte SQLite-Datei, Serverless ohne Streaming-Session über Minuten |
| **F. Diese Arena-Vorschau** | 0 Min | 0 € | ⚠️ | Session-gebunden | **hier blockt die Sandbox `openrouter.ai`** – UI, Beispiele, Rechenkern und Export laufen, Chat antwortet mit Hinweis |

---

## 2. Weg A – in 5 Minuten öffentlich (0 €, empfohlen)

Voraussetzung: der Rechner hat Internetzugang zu `openrouter.ai` (die Sandbox hier **nicht**).

```bash
# 1) App starten
cd SusMob
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
cp .env.example .env            # OPENROUTER_API_KEY eintragen
.venv/bin/python -m uvicorn server.main:app --host 0.0.0.0 --port 8080

# 2) Zweites Terminal: öffentliche HTTPS-URL erzeugen (kostenlos, kein Konto)
cloudflared tunnel --url http://localhost:8080
#   → gibt https://zufallsname.trycloudflare.com aus – dieser Link ist live
```

Alternativen mit dauerhafter URL: `tailscale funnel 8080` (eigene Domain möglich) oder
`ngrok http 8080` (Free-Konto, URLs wechseln).

```env
# .env für einen öffentlichen Test empfehlen sich:
SUSMOB_DEMO_ONLY=1                 # Banner: keine echten Daten mit Gratis-Modellen
SUSMOB_DAILY_REQUEST_BUDGET=50     # Gratis-Tier: 50 Requests/Tag
SUSMOB_CHAT_LIMIT_PER_HOUR=8       # schützt das Kontingent vor einzelnen Besuchern
ADMIN_PASSWORD=...                 # Admin-Bereich schützen (Prompt-Editor!)
SUSMOB_MAX_MESSAGE_CHARS=8000
```

---

## 3. Weg B – Render.com (URL ohne eigenen Rechner)

1. Repository zu GitHub pushen (Datei `render.yaml` liegt bei).
2. Render → **New → Blueprint** → Repo wählen. Der Blueprint legt einen Free-Webservice an.
3. Im Dashboard die geheimen Variablen setzen: `OPENROUTER_API_KEY`, `ADMIN_PASSWORD`.
4. Deploy abwarten → `https://susmob-test.onrender.com`.

```
buildCommand : pip install -r requirements.txt
startCommand : uvicorn server.main:app --host 0.0.0.0 --port $PORT
healthcheck  : /healthz
```

**Wichtig:** Im Free-Plan ist das Dateisystem flüchtig – nach Redeploy/Neustart sind Uploads,
Verlauf und Artefakte weg (Beispiele und Prompts werden neu geseedet). Für Tests okay; für
Dauerhaftigkeit ein Volume/Disk mounten und `SUSMOB_DATA_DIR=/pfad/zum/volume` setzen.

---

## 4. Weg C/D – Hugging Face Spaces bzw. Fly.io

**Hugging Face Space (Docker):** neues Space vom Typ *Docker* anlegen, das mitgelieferte
`Dockerfile` wird automatisch gebaut; Secrets im Space unter *Settings → Repository secrets*
(`OPENROUTER_API_KEY`, `ADMIN_PASSWORD`). Port `8080` ist korrekt voreingestellt.
Persistenz nur mit kostenpflichtigem „Persistent Storage" (dann `SUSMOB_DATA_DIR=/data`).

**Fly.io:**
```bash
fly launch --no-deploy          # nutzt das Dockerfile
fly volumes create susmob_data --size 1
fly secrets set OPENROUTER_API_KEY=sk-or-... ADMIN_PASSWORD=...
# fly.toml: [mounts] source="susmob_data" destination="/app/data"
fly deploy
```

**Docker überall sonst:**
```bash
docker build -t susmob .
docker run -d -p 8080:8080 -v susmob_data:/app/data \
  -e OPENROUTER_API_KEY=sk-or-... -e ADMIN_PASSWORD=geheim -e SUSMOB_DEMO_ONLY=1 susmob
```

---

## 5. Kosten im Testbetrieb

| Posten | Preis |
|---|---|
| Gratis-Modelle (OpenRouter `:free`) | **0 €**, aber 50 Requests/Tag (1.000/Tag ab 10 $ einmaligem Guthaben) |
| Hosting | 0 € (Tunnel/Render-Freiplan) bis ~3–5 €/Monat (Fly.io) |
| Domain (optional) | ~10 €/Jahr |
| **Erdung**: ein qualifizierter Chat mit Frontier-Modell | **0,04–0,12 $** (Plan, Abschnitt 3.3) |

Zum Vergleich: eine Fachplaner-Stunde kostet 80–120 €. Selbst 200 Chats/Monat mit einem
Frontier-Modell liegen bei ~25 $ – die Modellwahl ist eine Qualitäts-, keine Kostenfrage.

---

## 6. Betriebs-Checkliste für die Test-Instanz

- [ ] `ADMIN_PASSWORD` gesetzt (sonst ist der Prompt-Editor offen).
- [ ] `SUSMOB_DAILY_REQUEST_BUDGET` gesetzt (Kontingent schützen).
- [ ] `SUSMOB_CHAT_LIMIT_PER_HOUR` gesetzt (einzelne Besucher bremsen).
- [ ] `SUSMOB_DEMO_ONLY=1`, wenn Dritte Zugriff haben.
- [ ] OpenRouter-Privatsphäre-Einstellung prüfen: „Free-Modelle dürfen Trainingsdaten erhalten" – bewusst entscheiden.
- [ ] `#/admin → 🩺 Modell-Health` einmal ausführen (Fallback-Ketten prüfen).
- [ ] `/healthz` als Health-Check beim Hoster eintragen.
- [ ] Backup: `data/` (susmob.db, uploads, artifacts) sichern.

---

## 7. Was in dieser Sandbox sichtbar ist

Dieser Arbeitsbereich hat **keinen ausgehenden Zugriff auf `openrouter.ai`** (nur PyPI ist
erreichbar). Deshalb:

* funktionieren **Beispiele, Oberfläche, Standardwerte, Admin, Rechenkern, Auswertung,
  Excel/JSON-Export und Druckansicht** vollständig,
* antwortet der freie Chat mit dem klaren Hinweis auf die Netzsperre,
* zeigt `#/admin → 🩺 Modell-Health` „nicht erreichbar" als Status – auf einem Rechner mit
  Internet liefert dieselbe Ansicht Endpunktzahlen und Uptime.

Für echte Modell-Antworten die Datei `.env` (mit eingetragenem Key) auf einen Rechner mit
Internetzugang kopieren und dort starten – oder eine der Optionen A–D nutzen.
