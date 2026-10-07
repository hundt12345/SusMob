# SusMob – Bewertung & Plan (Arbeitsdokument)

**Stand des Plans:** 06.10.2026 · **Umsetzungsstand:** siehe unten (Status je Phase)
**Grundlage:** Messungen am laufenden System, Live-Abfragen der OpenRouter-Modell-API,
öffentliche Benchmarks. Token-Zahlen im Originalplan sind Schätzungen (±25 %) – ab
Phase 0 werden sie durch echte Messwerte aus `llm_calls` ersetzt.

---

## Umsetzungsstand (was ist gebaut)

| Phase | Inhalt | Status |
|---|---|---|
| **0** Betriebssicherheit & Messbarkeit | Modell-Health-Check je Kachel, Fallback-Kette (3 Modelle), 429-Backoff mit `Retry-After`, `llm_calls`-Tabelle + Kostenmessung, Audit-Log, klare Fehlerbilder | **umgesetzt** – `server/health.py`, `server/llm.py`, `server/telemetry.py`, Admin → „📈 Kosten, Health & Eval“ |
| **1** Ergebnis-Export | JSON-Schema je Kachel + Pydantic-Validierung + Reparaturprompt, Artefakt-System, Excel (Formeln + Annahmen-Blatt + Chart), CSV/JSON/Markdown, serverseitige SVG-Diagramme, PDF als Druck-CSS | **umgesetzt** – `server/schemas.py`, `server/export.py`, `POST /api/conversations/{id}/ergebnis`, `POST …/export?format=…` |
| **2** Rechenkerne & QS | Rechner in Python für CO₂-Bilanz, ÖPNV-Umlauf, TCO, Kostenband, Gefahrenstellen-Ranking, Ladebedarf, Parkraum; Eval-Harness mit Bewertungsschema; Rolling Summary für lange Chats | **umgesetzt** – `server/rechner.py`, `server/eval.py`, `tests/` (38 Tests) |
| **3** Neue Kacheln | Verkehrssicherheit/Schulweg, Ladeinfrastruktur, Parkraum – je mit Prompt, Standardwerten, Testfall, Beispiel, Rechenkern | **umgesetzt** – `server/seed.py`, `server/examples_extra.py` (10 Kacheln) |
| **4** Produktionsreife | Dockerfile, Compose + Caddy (TLS), `render.yaml`, `/healthz`, Betriebs-/Deploy-Doku, Datenschutz-Schalter für Gratis-Modelle | **teilweise** – Auth/Mandantenfähigkeit (Mehr-Kommunen-Betrieb, Rollen) und AVV-Prozess **offen** |
| Bild-Input | Bilder werden nicht mehr verworfen, sondern als multimodale Nachricht an Vision-Modelle gegeben (`gemma-4-31b-it:free`, `inkling:free`) | **umgesetzt** – `server/files.py`, Chat-Pipeline |
| Bildgenerierung | Illustrationen über Bildmodelle | **offen** (Kostenklärung nötig) |
| Karten/Geodaten | OSM-Kacheln mit Namensnennung, amtliche Geodaten | **offen** (Rechtsfrage, siehe Entscheidungen) |

**Offene Punkte, die eine Entscheidung brauchen:** Datenschutzfreigabe für Gratis-Provider,
Zielgruppe (Einzelkommune vs. Mehr-Mandanten-Produkt), Corporate Design für PDF-Vorlagen,
lizenzierte Geodaten, Mandantenfähigkeit/Rollen (Phase 4).

---

## 0. Kurzfazit (Originalplan)

1. **Gratis-Modelle tragen die Kacheln fachlich** (Index 40–48 vs. Frontier 52–61); die Lücke
   zeigt sich bei **Rechenaufgaben, Quellensicherheit und langen Formal-Dokumenten**.
2. **Kosten sind kein Argument für Gratis-Modelle**: ein qualifizierter Chat kostet mit
   Frontier-Modellen 0,04–0,12 $ – der echte Knappheitsfaktor sind **50 Requests/Tag**
   (≈ 8 qualifizierte Chats/Tag).
3. **Qwen-Fund**: `qwen/qwen3.8-27b:free` hatte keinen aktiven Provider – die Kachel wäre live
   gescheitert. Alle Kacheln laufen jetzt auf Modellen mit bestätigtem Endpunkt, abgesichert
   durch Health-Check + Fallback-Kette.
4. **Für Excel/PDF/Bild ist keine Export-Schaltfläche nötig, sondern eine Architekturänderung:**
   Zahlen entstehen **im Code** (deterministisch, mit Formeln), das LLM formuliert nur.
5. **Reihenfolge:** Phase 0 → 1 → 2 … (Betrieb + Export zuerst, dann Rechenkerne, dann Kacheln).

## 1. Status quo (vorher → jetzt)

| Bereich | vorher | jetzt |
|---|---|---|
| Kacheln | 7 | **10** (+ Verkehrssicherheit, Ladeinfrastruktur, Parkraum) |
| Modelle | 7 Gratis-Modelle, Qwen ohne Endpunkt | 7 Modelle in Ketten, **Fallback je Kachel**, Health-Check |
| Bild-Input | nicht vorhanden (Bilder verworfen) | **multimodal** an Vision-Modelle |
| Ergebnis-Export | nicht vorhanden | **Excel (Formeln), CSV, JSON, Markdown, SVG, Druck-HTML/PDF** |
| Token-/Kostenmessung | nicht vorhanden | **`llm_calls`** je Request: Tokens, Kosten, Dauer, Fallback |
| Nachvollziehbarkeit | keine | **Audit-Log** + Eval-Harness |
| Rechnen | im LLM | **Python-Rechenkerne**, LLM formuliert |

Gemessene Prompt-Größen (Zeichen aus der DB, unverändert gültig): System-Prompts
1.277–2.239 Zeichen (≈ 500–830 Tokens) plus Standardwerte; die Prompts sind nicht das
Kostenproblem – die Historie ist es (Abschnitt 3).

## 2. Qualität der Free Models

* **Rate-Limits:** ~20 Requests/Minute, **50 Requests/Tag**; ab 10 $ einmaligem Guthaben
  1.000/Tag.
* **Datenverarbeitung:** Free-Provider dürfen Prompts zum Training nutzen → echte
  Kommunaldaten nicht ohne Freigabe. Schalter: `SUSMOB_MODE=produktion`,
  `SUSMOB_ALLOW_FREE_FOR_DATA=0` (App verweigert dann Gratis-Modelle).
* **Verfügbarkeit:** Uptime 96–100 %, Modelle verschwinden (Qwen) → Health-Check + Kette.
* **Kachel-Fit (Plan):** Ultra/Super/Inkling für Konzept und komplexe Entwürfe, Gemma für
  Katalog-/Textarbeit und Bild-Input, Lightning für Kurztexte, Apodex/Nemotron Super für
  Formal-Dokumente und schema-treue Ausgabe.
* **Systemische Schwächen:** Arithmetik ohne Werkzeug, Quellen-/Fristensicherheit,
  JSON-Disziplin, lange Formal-Dokumente, Datenschutz.
  → Gegenmaßnahmen sind umgesetzt: Rechenkerne, „Quelle prüfen“-Pflicht, Structured Output
  mit Validierung + Reparaturpfad, Datenschutz-Schalter.

**Modell-Politik (umgesetzt):** Demo/Entwicklung/öffentliche Daten → Gratis; Enddokumente und
vertrauliche Daten → bezahltes Modell mit AVV; strukturierte Artefakte → Modelle mit
`structured_outputs` oder Code-first.

## 3. Token-Nutzung & Kosten pro qualifiziertem Chat

Methodik: qualifizierter Chat = Verlauf mit prüfbarem Ergebnis. Profil A: 3 Requests,
250 Zeichen Frage, 2.600 Zeichen Antwort, 1 Datei. Profil B: 6 Requests, 300 Zeichen Frage,
3.000 Zeichen Antwort, 2 Dateien. Formel (API ist zustandslos):

```
Input  = n · (System + Dateien) + (Frage + Antwort) · n·(n−1)/2
Output = n · Antwortlänge
```

| Preisklasse | Profil A | Profil B |
|---|---|---|
| Gratis-Modelle | 0,00 $ | 0,00 $ (3 bzw. 6 der 50 Tages-Requests) |
| Günstig (Gemma-Klasse, 0,09/0,34 $/Mio) | 0,001–0,002 $ | 0,004–0,005 $ |
| Günstig (Nemotron Ultra, 0,50/2,20 $/Mio) | 0,009–0,010 $ | 0,028–0,029 $ |
| Frontier (2/10 $/Mio) | 0,039–0,041 $ | 0,120–0,124 $ |

Szenarien (7 Kacheln, Profil B, Frontier): 35 Chats/Monat = 4,26 $ · 70 Chats = 8,53 $ ·
210 Chats = 25,58 $. Eine Fachplaner-Stunde kostet 80–120 € → Modellwahl ist eine
**Qualitäts-**, keine Kostenfrage.

**Ab jetzt gilt:** Diese Schätzungen sind durch Messwerte ersetzbar – Admin →
„📈 Kosten, Health & Eval“ zeigt Kosten je Kachel, je Modell, je Tag und je Unterhaltung.

**Sechs Hebel zur Token-Reduktion:** Rolling Summary (**umgesetzt**, ab 26 Nachrichten),
Prompt-Kürzung (offen), intelligente Dateikürzung (offen), Structured State (umgesetzt über
Ergebnisdokument), Modell-Routing (offen), Caching-fähige Anbieter bei Paid (offen).

## 4. Excel, PDF und Bild

* **Fundament (umgesetzt):** JSON-Schema je Kachel → Pydantic-Validierung → bei Fehlern
  **ein** Reparaturprompt → danach erst Fehlermeldung. Datenfluss:
  Datei/Text → LLM-Extraktion → **Python-Berechnung** → LLM-Formulierung → Renderer →
  Artefakt in DB + Download-Endpunkt.
* **Excel (umgesetzt):** `openpyxl` (bereits Abhängigkeit). Blätter `Annahmen` (editierbare
  Faktoren), `Eingangsdaten`, `Bilanz` mit **Zellformeln** auf das Annahmen-Blatt, `Maßnahmen`,
  Diagramm im Blatt; Zahlen als Zahlen, Einheiten in Kopfzeilen, Zellkommentare mit Quelle.
* **PDF (umgesetzt, Weg A):** Druck-CSS (`@page A4`, Kopf-/Fußzeile) + „Als PDF speichern“.
  WeasyPrint (Weg B) bleibt Option, sobald Briefkopf/Anlagenverzeichnis-Vorlagen nötig sind.
* **Bild (teilweise umgesetzt):** Diagramme serverseitig als SVG (Donut/Balken, ohne
  Fremdbibliothek), Bild-**Input** multimodal; Bildgenerierung und Geodaten offen.
* **Architekturempfehlung „Rechnen im Code, formulieren im LLM“ (umgesetzt):**
  Rechenkerne für CO₂-Bilanz, ÖPNV-Umlauf, TCO, Kostenband, Gefahrenstellen-Ranking,
  Ladebedarf, Parkraum. Der System-Prompt enthält den Abschnitt
  „Vorberechnete Werte (verbindlich, nicht nachrechnen)“.

## 5. Weitere sinnvolle Kacheln

| # | Kachel | Status |
|---|---|---|
| 1 | Verkehrssicherheit & Schulwegsicherheit | **gebaut** (Kachel + Unfall-CSV-Parser + Ranking) |
| 2 | Ladeinfrastruktur-Konzept | **gebaut** (Kachel + Bedarfsrechner) |
| 3 | Parkraum & Parkraumbewirtschaftung | **gebaut** (Kachel + Wirtschaftlichkeitsrechner) |
| 4 | Modal-Split & Mobilitätsbefragung (Monitoring) | offen (1,5 Tage) |
| 5 | Verkehrsversuch & Verkehrsberuhigung | offen (1 Tag) |
| 6 | On-Demand-/Rufbus-Konzept | offen (1,5 Tage) |
| 7 | Stadtbahn/SPNV-Anschluss & Bike+Ride | offen (1 Tag) |
| 8 | Wirtschaftsverkehr & City-Logistik | offen (1,5 Tage) |
| 9 | Förder-Radar & Fristenkalender | offen (1,5 Tage + Datenpflege) |
| 10 | Kommunale E-Flotte & TCO-Vergleich | Rechner vorhanden (TCO), Kachel offen |
| 11 | Luftreinhaltung & Lärmaktionsplan | offen (1,5 Tage) |
| 12 | Klimaanpassung & Hitzeaktionsplan | offen (1,5 Tage) |

## 6. Phasenplan (Originalzeitplan)

| Woche | Inhalt | Ergebnis | Status |
|---|---|---|---|
| 1 | Phase 0 | stabile Chats, echte Kostenmessung | umgesetzt |
| 2–3 | Phase 1 | Excel/PDF/Diagramme aus dem Chat | umgesetzt |
| 4 | Phase 2 | nachrechenbare Zahlen, Eval-Set | umgesetzt |
| 5–6 | Phase 3 | 3 neue Kacheln | umgesetzt |
| 7–8 | Phase 4 | mandantenfähig, DSGVO-Argumente, Deploy | teilweise (Deploy ja, Multi-Tenant offen) |

**Kennzahlen zum Steuern** (Messung jetzt im Admin sichtbar): Modellausfälle < 2 je 100 Chats ·
Kosten je qualifiziertem Chat < 0,15 $ · Token je Ergebnisdokument −30 % · Export-Zeit < 30 s ·
Testfälle ohne erfundene Zahlen ≥ 90 % · 10/10 Beispiele vorhanden.

## 7. Risiken

| Risiko | Gegenmaßnahme | Status |
|---|---|---|
| Gratis-Modell verschwindet | Health-Check + Fallback-Kette | umgesetzt |
| Tageslimit 50 Requests | 10-$-Guthaben oder Paid-Tarif | dokumentiert |
| Free-Provider trainiert mit Prompts | Freigabe oder Paid/AVV, Sperrschalter | Schalter umgesetzt |
| Erfundene Fördersätze/Fristen | „Quelle prüfen“-Pflicht, Eval-Kriterium | umgesetzt (Prompts + Eval) |
| Rechenfehler in Antworten | Rechner im Code | umgesetzt |
| Geodaten ohne Lizenz | nur OSM mit Namensnennung oder Lizenz | offen |
| Token-Kostenexplosion bei großen Dateien | Rolling Summary, Obergrenzen | teilweise |
| Prompt-Änderung verschlechtert Qualität | Eval-Harness als Regression | umgesetzt |

## 8. Entscheidungen, die gebraucht werden

1. **Datenschutz:** Dürfen Kommunaldaten an Free-Provider? Sonst Paid/AVV oder Self-Hosting.
2. **Zielgruppe:** Einzelkommune (Beratung) oder Mehr-Mandanten-Produkt? → Phase 4.
3. **Budget:** Welche Kacheln fest auf Paid (Empfehlung: Beschlussvorlagen, Förderanträge)?
4. **Export-Vorlagen:** Gibt es Corporate Design (Briefkopf/Schrift)?
5. **Geodaten:** Welche Quellen sind lizenziert verfügbar?
6. **Priorität:** Phase 0+1 zuerst (erledigt) – oder weitere neue Kacheln für die Demo?

## 9. Erste drei konkrete Schritte (erledigt)

1. ✅ `llm_calls`-Tabelle + Usage-Logging → Kosten sind Messwerte.
2. ✅ Health-Check + Fallback-Kette → kein Kachel-Chat fällt mehr aus.
3. ✅ JSON-Schema + Excel-Export → erstes echtes Artefakt, Blaupause für die Formate.

---

*Hinweis: Token-Zahlen im Originalplan sind Schätzungen (±25 %). Nach Umsetzung von Phase 0
liefert `llm_calls` exakte Werte; die Admin-Auswertung zeigt sie je Kachel, Modell und Tag.*
