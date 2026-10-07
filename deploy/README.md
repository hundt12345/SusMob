# SusMob deployen – drei Wege, nach Aufwand sortiert

Die App ist eine einzelne FastAPI-Anwendung mit SQLite, ohne externe Dienste.
Sie braucht **ausgehendes HTTPS** zu `openrouter.ai` und ein Verzeichnis `data/`
für Datenbank, Uploads und Artefakte.

## Variante A – Tunnel von deinem Rechner (5 Minuten, 0 €)

```bash
cd SusMob
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
echo 'OPENROUTER_API_KEY=sk-or-...' > .env
.venv/bin/uvicorn server.main:app --host 0.0.0.0 --port 8080

# zweites Terminal: öffentliche URL erzeugen
cloudflared tunnel --url http://localhost:8080      # cloudflared installieren
# alternativ: ngrok http 8080
```
Die URL (`https://…trycloudflare.com`) ist sofort im Internet erreichbar, inklusive
Live-Chat. Ideal für Tests mit Kolleg:innen; der Rechner muss laufen.

## Variante B – Docker auf einem VPS (ab ca. 4 €/Monat, Dauerbetrieb)

```bash
# auf dem Server (Debian/Ubuntu, Docker installiert), Domain zeigt per A-Record auf den Server
git clone <repo> susmob && cd susmob
cp .env.example .env && nano .env          # OPENROUTER_API_KEY, ADMIN_PASSWORD, DOMAIN
DOMAIN=susmob.example.de docker compose --profile tls up -d
```
Caddy holt automatisch ein Let's-Encrypt-Zertifikat; Daten liegen im Volume
`susmob-data` (Backup: `docker run --rm -v susmob-data:/d -v $PWD:/b alpine tar czf /b/backup.tgz -C /d .`).

## Variante C – Plattform mit Git-Deploy (kostenlos startbar)

* **Render.com**: Repo verbinden, `render.yaml` wird erkannt. Free-Tarif hat keine
  persistente Platte – gut für eine Demo (Seed/Beispiele entstehen automatisch).
* **Fly.io**: `fly launch --dockerfile Dockerfile`, danach `fly volumes create data`
  und in `fly.toml` unter `[mounts]` `source="data" destination="/app/data"` setzen.

## Nach dem Deploy prüfen

```bash
curl -s https://DEINE-DOMAIN/healthz | python3 -m json.tool
# erwartet: ok=true, api_key=true, tiles=10
```
Im Admin-Bereich (`/#/admin/system`) „🩺 Jetzt prüfen“ starten: Der Health-Check zeigt,
ob die konfigurierten Modelle aktive Endpunkte haben.

## Betriebshinweise

* **Ein Prozess**: SQLite und die Admin-Tokens liegen im Prozess – nicht horizontal skalieren.
* **Backup**: `data/susmob.db` plus `data/uploads/` und `data/artifacts/` (WAL-Dateien mitnehmen).
* **Datenschutz**: Im Modus `produktion` (`SUSMOB_MODE=produktion`,
  `SUSMOB_ALLOW_FREE_FOR_DATA=0`) verweigert die App Chats über Gratis-Modelle.
* **Free-Tier-Limits**: ca. 50 Requests/Tag (1.000/Tag nach einmalig 10 $ Guthaben).
