# Schnell und günstig zur Test-Homepage mit Live-Chat

Kurzantwort: **Cloudflare-Tunnel für den Fünf-Minuten-Test, Hetzner-VPS mit Docker + Caddy
für den Dauerbetrieb (ab ca. 4 €/Monat), Render/Fly.io wenn es ohne Serverpflege laufen soll.**
Modellkosten: mit den `:free`-Modellen **0 €** – begrenzt durch 50 Requests/Tag (1.000/Tag nach
einmalig 10 $ Guthaben). Alles andere ist Hoster-Arbeit.

## Entscheidungshilfe

| Ziel | Weg | Kosten | Zeit | Dauerhaft? |
|---|---|---|---|---|
| Schnell Kolleg:innen zeigen | Tunnel von deinem Rechner (cloudflared/ngrok) | 0 € | ~5 min | nein (Rechner läuft) |
| Dauerhaft, eigene Domain, TLS | VPS + Docker Compose + Caddy | 4–6 €/Monat | ~30 min | ja, volle Kontrolle |
| Ohne Serverpflege, Git-Deploy | Render.com / Fly.io / Railway | 0 € startbar | ~10 min | Render-Free ohne persistente Daten |
| Nur intern im Amt | Docker auf einer vorhandenen Maschine + Reverse Proxy | 0 € | ~30 min | ja |

## Variante A – Fünf Minuten, 0 € (Tunnel)

```bash
cd SusMob
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
cp .env.example .env      # OPENROUTER_API_KEY eintragen
.venv/bin/uvicorn server.main:app --host 0.0.0.0 --port 8080

# zweites Terminal:
cloudflared tunnel --url http://localhost:8080
```

`cloudflared` gibt eine `https://…trycloudflare.com`-URL aus. Die ist sofort öffentlich,
inklusive Live-Chat – der Modell-Request geht vom **lokalen** Rechner an OpenRouter, es wird
kein Port im Router geöffnet. Nachteil: Dein Rechner und die App müssen laufen, die URL
wechselt bei jedem Start.

> Für kurze Vorführungen in der Arena-Sandbox gilt: Der Sandbox-Proxy
> (`https://{port}-{sandboxId}.e2b.app`) zeigt die Oberfläche, aber die Sandbox blockt
> ausgehende Verbindungen zu `openrouter.ai`. Der Chat antwortet dort mit dem Hinweis
> „OpenRouter ist von diesem Server aus nicht erreichbar“ – Beispiele, Rechner und Export
> funktionieren trotzdem vollständig.

## Variante B – Dauerbetrieb für ~4–6 €/Monat (empfohlen)

1. VPS bei Hetzner/Netcup/IONOS (kleinster Tarif reicht: 1 vCPU, 2 GB RAM, 20–40 GB SSD).
2. Domain-Subdomain per A-Record auf die Server-IP zeigen lassen (`test.example.de`).
3. Docker installieren, dann:

```bash
git clone <dein-repo> susmob && cd susmob
cp .env.example .env && nano .env      # OPENROUTER_API_KEY, ADMIN_PASSWORD setzen
DOMAIN=test.example.de docker compose --profile tls up -d
```

Caddy holt automatisch ein Let's-Encrypt-Zertifikat, leitet auf HTTPS um und puffert den
SSE-Stream des Chats nicht. Fertig: `https://test.example.de`.

**Backup** (SQLite + Uploads + Artefakte):

```bash
docker run --rm -v susmob_susmob-data:/d -v "$PWD":/b alpine tar czf /b/susmob-backup.tgz -C /d .
```

## Variante C – Ohne Serverpflege (Render / Fly.io)

* **Render.com**: `render.yaml` liegt im Repo → „New Web Service → Build from repository“
  erkennt den Docker-Build. Free-Tarif: keine persistente Platte, `data/` wird bei jedem
  Deploy neu angelegt (Beispiele und Seed entstehen automatisch; Chatverläufe und Artefakte
  sind dann weg). Secrets `OPENROUTER_API_KEY` und `ADMIN_PASSWORD` im Dashboard setzen.
* **Fly.io**: `fly launch --dockerfile Dockerfile` und danach ein Volume für `/app/data`
  anlegen (`fly volumes create susmob_data --size 1`), sonst verlierst du die Datenbank.

## Was die App selbst schon mitbringt

* **Dockerfile**, `docker-compose.yml` (App + Caddy), `deploy/Caddyfile`, `render.yaml`.
* `GET /healthz` für Monitoring und Plattform-Healthchecks (Tiles, API-Key, letzter Call).
* Admin → „📈 Kosten, Health & Eval“: Modell-Health-Check, Token-/Kostenmessung, Audit-Log,
  Eval-Harness. Damit siehst du nach dem Deploy sofort, ob die Modelle erreichbar sind.
* `SUSMOB_MODE=produktion` + `SUSMOB_ALLOW_FREE_FOR_DATA=0` sperrt Gratis-Modelle für
  echte Daten (Datenschutz, Plan Abschnitt 2.1/2.5).

## Stolperfallen (realistisch)

1. **Free-Tier-Limit**: 50 Anfragen/Tag = ca. 8 Ergebnis-Gespräche. Für eine Demo mit mehreren
   Personen lohnt das einmalige 10-$-Guthaben (1.000/Tag) oder ein günstiges Paid-Modell
   (0,001–0,005 $ je Chat).
2. **Datenschutz**: Gratis-Anbieter dürfen Prompts zum Training nutzen. Für echte
   Kommunaldaten entweder Freigabe einholen, Paid-Modell mit AVV wählen oder
   `SUSMOB_MODE=produktion` fahren.
3. **Eine Instanz**: SQLite und Admin-Tokens vertragen keine horizontalen Skalierung
   (kein `--workers 4`, kein Load Balancer mit mehreren Instanzen).
4. **SSE durch Proxys**: Puffern muss aus sein (`X-Accel-Buffering: no` setzt die App;
   Caddy: `flush_interval -1`).
5. **Ausgehendes HTTPS**: Manche streng gefilterte Netze blocken Modell-APIs. Der
   Health-Check im Admin zeigt das sofort an.
6. **Modell verschwindet**: Genau der Qwen-Fall aus dem Plan. Deshalb Fallback-Kette
   (3 Modelle je Kachel) + Health-Check; im Admin nach dem Deploy einmal prüfen.
