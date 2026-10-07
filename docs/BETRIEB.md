# SusMob online stellen – schnell und günstig (Test-Homepage mit Live-Chat)

Ziel: eine **im Internet aufrufbare Test-Seite** mit Live-Chat, die mit **Gratis-Modellen** läuft
und möglichst nichts kostet. Stand: 06.10.2026.

---

## 0. Drei Entscheidungen vorab

| Frage | Konsequenz |
|---|---|
| Sollen **fremde Besucher** chatten? | Ja → Tages-/Stundenlimit setzen (`SUSMOB_DAILY_REQUEST_BUDGET`, `SUSMOB_CHAT_LIMIT_PER_HOUR`) und `ADMIN_PASSWORD` setzen. |
| Gehen **echte Kommunaldaten** durch die Seite? | Nein → `SUSMOB_DEMO_ONLY=1` (Banner + Audit-Eintrag). Gratis-Provider dürfen Prompts zum Training nutzen. |
| Muss der **Verlauf erhalten** bleiben? | Ja → Hosting mit Volume/Dateisystem (Fly.io, eigener Server, Hugging Face mit Storage) oder Render mit bezahltem Instanztyp + Disk. Render-**Free** ist flüchtig und kann gar kein Disk anhängen. |

---

## 1. Überblick: Wege ins Netz

| Weg | Aufwand | Kosten | Live-Chat | Dauerhaftigkeit | Bewertung |
|---|---|---|---|---|---|
| **A. Eigener Rechner + Cloudflare Tunnel** | 5 Min | **0 €** | ✅ | solange PC läuft | **Empfehlung für schnelle Tests** – keine Kreditkarte, kein Sleep, volle SQLite-Persistenz |
| **B. Render (Free-Plan, Docker)** | 10 Min | 0 € (Sleep nach 15 min) | ✅ | FS flüchtig, **kein Disk im Free-Plan** | beste „echte" URL ohne eigenen Rechner |
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

### 3.1 Welche Runtime wählen? → **Docker**

Render bietet als Umgebung u. a. Node, Python, Go, Rust, Elixir und **Docker**. Für SusMob
**Docker** wählen, denn:

* Im Repo liegt ein `Dockerfile` → Render erkennt es und zieht die Umgebung selbst auf
  (Python 3.12 fixiert, keine Überraschungen durch Buildpack-Versionen).
* Der Port wird über `$PORT` gesteuert (Render setzt ihn, Standard `10000`) – das Dockerfile
  nutzt ihn bereits, also **nichts** an Ports konfigurieren.
* Health-Check läuft über `/healthz`, das im Image mitgeliefert ist.

Gleichwertige Alternative, falls du lieber nativ (ohne Docker) deployst – dann **Python 3**:

```
Build Command : pip install -r requirements.txt
Start Command : uvicorn server.main:app --host 0.0.0.0 --port $PORT
Health-Check  : /healthz
PYTHON_VERSION: 3.12.6   (als Umgebungsvariable)
```

### 3.2 Wo kommt der OpenRouter-Key hin?

**Nie ins Repo.** Zwei Wege:

**a) Beim Anlegen über den Blueprint (`render.yaml` vorhanden):** Die Datei enthält
`OPENROUTER_API_KEY` und `ADMIN_PASSWORD` mit `sync: false` – Render zeigt beim Durchklicken
des Blueprints genau diese Felder und fragt die Werte ab. Dort einfügen, fertig.

**b) Nachträglich (oder bei manuell angelegtem Service):**
Dashboard → **Service auswählen** → linke Leiste **Environment** → Abschnitt
**Environment Variables** → **+ Add Environment Variable**:

| Key | Value |
|---|---|
| `OPENROUTER_API_KEY` | `sk-or-v1-…` (dein Key) |
| `ADMIN_PASSWORD` | frei wählbares Admin-Passwort |

* **Add from .env** gibt es auch: damit lässt sich eine ganze `.env` einfügen (Massenimport).
* Beim **manuell** angelegten Web Service steht der Abschnitt „Environment Variables" im
  Anlegeformular unter **Advanced**.
* **Save changes** löst automatisch ein neues Deploy aus; der Wert ist danach maskiert und
  kann nur überschrieben, nicht mehr ausgelesen werden.

Wichtig zu wissen: Der Blueprint liest `render.yaml` aus dem gewählten **Branch** – unser Branch
heißt `arena/42800ec5-susmob` (entweder den beim Blueprint auswählen oder vorher nach `main` mergen).

### 3.3 Grenzen des Free-Plans (ehrlich)

* **512 MB RAM**, anteilige CPU; **schläft nach 15 Minuten ohne Zugriff** ein, Kaltstart ~1 Minute.
* **750 Freistunden pro Monat** je Workspace (ein durchlaufender Service ≈ 744 h – reicht also).
* **Kein Disk möglich:** Das Dateisystem ist flüchtig. Nach Spin-down oder Deploy sind Gespräche,
  Uploads und Exporte weg – **Kacheln, Prompts und die 7 Beispiele werden beim Start automatisch
  neu angelegt**, die Seite ist also nie „leer". Für einen Demo-Link völlig ausreichend.
* **Persistenz erst mit bezahltem Instanztyp** (Starter ab ~7 $/Monat) + Disk (0,25 $/GB/Monat):
  Disk auf `/app/data` mounten – das Dockerfile nutzt genau dieses Verzeichnis (alternativ
  `SUSMOB_DATA_DIR` auf den Mountpoint setzen).
* Ein Disk verhindert „Zero-Downtime-Deploys" – für Tests irrelevant.

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
| Hosting | 0 € (Tunnel/Render-Freiplan) bis ~3–5 €/Monat (Fly.io); Render mit Disk ab ~7 €/Monat |
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
- [ ] Backup: `data/` (susmob.db, uploads, artifacts) sichern – bei Render-Free entfällt das (flüchtig).
- [ ] Bei Render: Runtime **Docker**, Health-Check `/healthz`, Key im Dashboard unter *Environment*.

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
