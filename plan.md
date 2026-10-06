> **Umsetzungsstand in diesem Repository (06.10.2026):** Phase 0 vollständig, Phase 1 vollständig
> (Excel mit Formeln, JSON, PDF über Druck-CSS, Diagramme, Artefakt-Verwaltung), Phase 2 in
> wesentlichen Teilen (Rechenkerne für CO₂, ÖPNV, TCO, Kostenband, Priorisierung; Eval-Harness;
> Antworttext-Parser als netzunabhängiger Fallback). Phase 3 (neue Kacheln) und Phase 4
> (Multi-Tenancy, AVV-Anbieter) sind offen. Details: `README.md`, Betrieb/Hosting: `docs/BETRIEB.md`.
> Konkrete Abweichungen zur Planung: Der Rechenkern wurde vorgezogen (Phase 2 → Phase 1), weil der
> Excel-Export sonst keine belastbaren Zahlen hätte; PDF startet mit Druck-CSS (Weg A), WeasyPrint
> mit echten Vorlagen bleibt offen. Der Qwen-Fund aus Abschnitt 0.3 ist behoben (Migration
> `TOTE_DEFAULT_MODELLE`), die Fallback-Ketten liegen in `server/seed.py → FALLBACK_KETTEN`.

---

# SusMob – Bewertung & Plan

**Stand:** 06.10.2026 · **Grundlage:** Messungen am laufenden System (Prompt-/Antwortlängen aus der Datenbank),
Live-Abfragen der OpenRouter-Modell-API (Endpunkte, Limits, Parameter, Preise) und öffentliche Benchmarks.
Alle Token-Zahlen sind **Schätzungen** (±25 %), weil die genauen Tokenizer-Vokabulare in dieser Umgebung
nicht ladbar sind (Beschreibung der Methodik in Abschnitt 3.1).

---

## 0. Kurzfazit

1. **Die Gratis-Modelle tragen die Kacheln fachlich** – für Entwürfe, Strukturierung und Erstfassungen liegen
   sie 40–48 Punkte auf dem Artificial-Analysis-Intelligence-Index, Frontier-Modelle bei 52–61. Der Abstand
   zeigt sich bei **Rechenaufgaben, Quellensicherheit und langen Formal-Dokumenten**, nicht beim Aufbau.
2. **Kosten sind kein Argument für Gratis-Modelle.** Ein qualifizierter Chat kostet selbst mit Frontier-Modellen
   **0,04–0,12 $** – das sind 0,05–0,15 % einer Fachplaner-Stunde. Der echte Knappheitsfaktor der Gratis-Tarife ist
   nicht Geld, sondern **50 Requests/Tag** – das sind etwa **8 qualifizierte Chats pro Tag für die ganze Stadt**.
3. **Ein akutes Problem wurde gefunden und behoben:** `qwen/qwen3.8-27b:free` hatte keinen aktiven Provider
   (leere Endpunktliste). Die Kachel „Beschlussvorlagen" wäre live fehlgeschlagen. Alle sieben Kacheln sind jetzt
   auf Modelle mit bestätigtem Endpunkt und 96–100 % Uptime umgestellt.
4. **Für Excel/PDF/Bild ist nicht „ein Export-Button" nötig, sondern eine Architekturänderung:** Zahlen müssen
   **im Code** entstehen (deterministisch, prüfbar, mit Formeln), das LLM formuliert und strukturiert nur.
   Damit werden Excel, PDF und Diagramme zu 80 % ein Daten-, nicht ein KI-Problem.
5. **Empfehlung:** Phase 0 (Betriebssicherheit + Kostenmessung) und Phase 1 (Structured Output + Export)
   zuerst – Aufwand ~8–13 Personentage, danach ist SusMob vorzeigbar für echte Kommunen.

---

## 1. Status quo

| Bereich | Zustand |
|---|---|
| Kacheln | 7, je mit Fach-Prompt, Standardwerten, Testfall und schreibgeschütztem Beispiel |
| Modelle | 7 verschiedene Gratis-Modelle, Live-Liste im Admin, Fallback offline |
| Betrieb | FastAPI + SQLite (WAL), `.env`-Loader, Admin mit Prompt-Versionierung |
| Datei-Input | Text-Extraktion aus txt/csv/xlsx/docx/pdf (max. 12.000 Zeichen je Datei, 48.000 gesamt) |
| **Bild-Input** | **nicht vorhanden** – Anhänge werden nur textuell ausgewertet |
| **Ergebnis-Export** | **nicht vorhanden** – Ergebnis lebt im Chat-Markdown |
| Token-/Kostenmessung | **nicht vorhanden** – Zahlen in diesem Dokument sind Schätzungen |

### 1.1 Gemessene Prompt-Größen (echte Zeichen aus der DB)

| Kachel | System-Prompt | Std.-Werte | **System total pro Request** | ≈ Tokens (3,3 Z/T) |
|---|---|---|---|---|
| CO₂-Bilanz | 2.239 | 103 | **2.737** | ~830 |
| Beschlussvorlagen & Förderanträge | 1.930 | 26 | **2.348** | ~712 |
| Klimaschutzkonzept | 1.733 | 79 | **2.205** | ~668 |
| Maßnahmenplanung Mobilität | 1.954 | 29 | **2.375** | ~720 |
| Wegeplanung Fahrrad | 1.803 | 86 | **2.282** | ~692 |
| Argumentationshilfe intern | 1.277 | 22 | **1.691** | ~512 |
| ÖPNV-Planung | 1.686 | 0 | **2.077** | ~629 |

Die Prompts sind **angemessen schlank** (500–830 Tokens). Sie sind nicht das Kostenproblem – die Historie ist es
(Abschnitt 3.6).

---

## 2. Qualität der Free Models

### 2.1 Was „gratis" bei OpenRouter real bedeutet

| Aspekt | Fakt (Stand 06.10.2026) | Konsequenz für SusMob |
|---|---|---|
| Rate-Limits | ~20 Requests/Minute, **50 Requests/Tag**; ab 10 $ einmaligem Guthaben 1.000/Tag | 50 Requests ≈ **8 qualifizierte Chats/Tag** für alle Kacheln zusammen |
| Datenverarbeitung | Free-Provider dürfen Prompts zum Training nutzen (abschaltbar in den OpenRouter-Privatsphäre-Einstellungen, dann ggf. weniger Endpunkte) | **Echte Kommunaldaten gehören nicht in Free-Modelle** ohne Freigabe |
| Verfügbarkeit | Uptime der genutzten Anbieter 96–100 %, aber Modelle verschwinden (siehe Qwen) | Health-Check + Fallback-Kette nötig |
| Qualitätsschwankung | Reasoning-Modelle mit variablem „Denkaufwand", Temperatur unterschiedlich unterstützt | Ergebnisse streuen stärker als bei Frontier-Modellen |
| Caching | **kein** implizites Prompt-Caching bei allen sieben Modellen | kein Kostenvorteil, aber bei Gratis-Tarif irrelevant |

### 2.2 Steckbriefe der eingesetzten Gratis-Modelle (Live-API-Werte)

| Modell | Kontext | Max. Output | Tools | Structured Outputs | Bild-Input | Uptime 1d | Stärke / Schwäche |
|---|---|---|---|---|---|---|---|
| `nvidia/nemotron-3-ultra-550b-a55b:free` | 1.000k | 65k | ✅ | ❌ (nur Tools) | ❌ | 96,2 % | Stärkstes US-Open-Modell (Index 48), gute Rechenbegleitung; Uptime niedrig |
| `nvidia/nemotron-3-super-120b-a12b:free` | 262k | 236k | ✅ | ✅ | ❌ | 99,9 % | Zuverlässig, JSON-schematreu – gut für Tabellen/Struktur |
| `thinkingmachines/inkling:free` | 1.048k | 262k | ✅ (eingeschränkt) | ❌ | ✅ (Bild/Audio) | 99,3 % | Top-Qualität offener Gewichte (Index 41), langer Kontext; Tool-Choice eingeschränkt |
| `apodex/apodex-1.1-mini:free` | 262k | 236k | ✅ | ✅ | ❌ | ~100 % | Formal-Dokumente + schematreue Ausgabe; wenig verbreitet, geringe Betriebserfahrung |
| `google/gemma-4-31b-it:free` | 262k | 33k | ✅ | nur `response_format` | ✅ | 99,9 % | Sehr stabil, multimodaler Input; qualitativ eine Klasse unter Ultra/Inkling (Index 39) |
| `google/gemma-4-26b-a4b-it:free` | 262k | 33k | ✅ | nur `response_format` | ✅ | 99,5 % | Schnell (3,8B aktiv), gut für Katalog-/Textarbeit; schwächer beim Rechnen |
| `nvidia/nemotron-3.5-lightning:free` | 1.000k | 65k | ✅ | ❌ | ❌ | 98,0 % | Sehr schnell (3B aktiv) – ideal für Argumentations-/Kurztexte; geringste Tiefe |

Qualitätsrangfolge (Artificial-Analysis-Intelligence-Index, verschiedene Index-Versionen):
**Inkling ≈ Nemotron 3 Ultra (41–48) > Nemotron 3 Super (36) > Gemma 4 31B (39/14,7 je Skala) > gpt-oss-120b (33)**.
Frontier-Vergleich: Opus-Klasse 61, Kimi K2.6 54, GPT-6.1 Sol 51,8 – die Lücke beträgt also **10–20 Indexpunkte**.

### 2.3 Kachel-Fit – ehrliche Bewertung

| Kachel | Modell | Fit | Begründung / Risiko |
|---|---|---|---|
| CO₂-Bilanz | Nemotron 3 Ultra | **gut** | Struktur + Tabellen sitzen; **Rechenfehler möglich** → Rechnen gehört in den Code (Abschnitt 4.5) |
| Beschlussvorlagen | Apodex 1.1 Mini | **gut** | Formalaufbau und Konjunktiv korrekt; Förderdaten bleiben Annahmen → „Quelle prüfen"-Pflicht |
| Klimaschutzkonzept | Inkling | **gut** | 1M Kontext für Altkonzept + Dateien; gutachterliche Struktur stimmt |
| Maßnahmenplanung | Gemma 4 26B A4B | **ausreichend** | Katalogqualität okay, Priorisierung wird gern gleichförmig; bei Bedarf auf Inkling/Ultra hochstufen |
| Wegeplanung | Gemma 4 31B | **ausreichend** | Regelwerk (FAVR/StVO) korrekt referenziert; Abschnittsdetails brauchen Prüfung. Vorteil: **Bild-Input** für Bestandsfotos |
| Argumentation | Nemotron 3.5 Lightning | **gut** | Kurze, pointierte Texte; Quellenangaben bleiben dünn → Prompt diszipliniert bereits |
| ÖPNV-Planung | Nemotron 3 Super | **gut** | Umlauf-/Taktlogik nachvollziehbar, Tabellen stabil |

### 2.4 Wo Gratis-Modelle systemisch scheitern

1. **Arithmetik ohne Werkzeug** – Bilanzen, Umlaufzeiten, Kostenbänder: einzelne Werte kippen.
   Lösung: Rechenkern im Python-Code, LLM erhält fertige Zahlen.
2. **Quellen- und Fristensicherheit** – Förderprogramme, Fördersätze, Fristen: Modelle erfinden plausible Details.
   Der Prompt verbietet es, die Modelle halten sich nur teilweise daran. Lösung: Förderdatenbank als Datei/Pflege + „Quelle prüfen"-Pflichtfeld.
3. **JSON-Disziplin** – nur Nemotron 3 Super und Apodex unterstützen echtes `structured_outputs`; Gemma nur `response_format`.
   Für Excel/PDF-Erzeugung ist das der entscheidende Unterschied (Abschnitt 4.1).
4. **Lange Formal-Dokumente** – ab ~6.000 Zeichen Ausgabe brechen Struktur und Konjunktiv punktuell weg.
5. **Datenschutz** – Training mit Free-Prompts. Ohne Freigabe ist das für echte Kommunaldaten **nicht** vertretbar.

### 2.5 Empfohlene Modell-Politik

| Zweck | Modellklasse | Begründung |
|---|---|---|
| Demo, Testfälle, Prompt-Entwicklung, öffentliche Daten | Gratis | kostenlos, ausreichend, transparent |
| Entwurf und Struktur mit moderaten Daten | Gratis + **Fallback-Kette** (3 Modelle in Prioritätsreihenfolge) | Verfügbarkeitsrisiko abfangen |
| Enddokumente (Beschlussvorlage, Förderantrag) und vertrauliche Daten | bezahltes Modell mit AVV + **Prompt-Caching** | Haftung, Quellentreue, Datenschutz; Kosten bleiben < 0,15 $/Chat |
| Strukturierte Artefakte (Excel/JSON) | Modelle mit `structured_outputs` (Nemotron 3 Super, Apodex) oder Code-first | Schema-Validierung verhindert Stillbruch |

**Neu einzubauen (Phase 0):** Ein Health-Check, der beim Start und im Admin prüft, ob das je Kachel konfigurierte
Modell **aktive Endpunkte** hat, und bei Ausfall automatisch auf das nächste Modell der Kette ausweicht –
genau der Fehler, der Qwen heute unbrauchbar machte, wäre damit sichtbar und unkritisch.

---

## 3. Token-Nutzung & Kosten pro qualifiziertem Chat

### 3.1 Methodik

Ein **qualifizierter Chat** = Verlauf, der ein prüfbares Ergebnis liefert (Rückfragen → Daten → Ergebnis → Nachbesserung).
Zwei Profile als Rechengrundlage:

- **Profil A – Kurzberatung mit Ergebnis:** 3 Requests, je 250 Zeichen Frage, 2.600 Zeichen Antwort, 1 Datei (4.000 Zeichen).
- **Profil B – Ergebnisdokument:** 6 Requests, je 300 Zeichen Frage, 3.000 Zeichen Antwort, 2 Dateien (8.000 Zeichen).

Formel (die API ist zustandslos – **der komplette Kontext wird bei jedem Request erneut gesendet**):

```
Input   = n · (System + Dateien) + (Frage + Antwort) · n·(n−1)/2
Output  = n · Antwortlänge
```

Token-Schätzung: deutsche Fachtexte ≈ **3,0–3,8 Zeichen/Token**; gerechnet mit **3,3** (Mittel), Unsicherheit ±25 %.
Preise: Gemma 4 31B 0,09/0,34 $/Mio · Nemotron Ultra 0,50/2,20 $/Mio · Frontier (Claude Sonnet 5.5 / GPT-6.1 Sol) 2/10 $/Mio.

### 3.2 Tokens je qualifiziertem Chat (Profil A / B)

| Kachel | A: Input | A: Output | B: Input | B: Output |
|---|---|---|---|---|
| CO₂-Bilanz | 8.715 | 2.364 | 34.522 | 5.455 |
| Beschlussvorlagen | 8.362 | 2.364 | 33.815 | 5.455 |
| Klimaschutzkonzept | 8.232 | 2.364 | 33.555 | 5.455 |
| Maßnahmenplanung | 8.386 | 2.364 | 33.864 | 5.455 |
| Wegeplanung | 8.302 | 2.364 | 33.695 | 5.455 |
| Argumentation | 7.765 | 2.364 | 32.620 | 5.455 |
| ÖPNV-Planung | 8.115 | 2.364 | 33.322 | 5.455 |

### 3.3 Kosten je qualifiziertem Chat

| Preisklasse | Profil A | Profil B | Bemerkung |
|---|---|---|---|
| **Gratis-Modelle** | **0,00 $** | **0,00 $** | bezahlt wird mit 3 bzw. 6 der 50 Tages-Requests |
| Günstig (Gemma 4 31B: 0,09/0,34 $/Mio) | 0,001–0,002 $ | 0,004–0,005 $ | sogar für Massennutzung irrelevant |
| Günstig (Nemotron Ultra: 0,50/2,20 $/Mio) | 0,009–0,010 $ | 0,028–0,029 $ | gutes Preis-Leistungs-Verhältnis |
| Frontier (2/10 $/Mio) | 0,039–0,041 $ | 0,120–0,124 $ | Enddokumente, sensible Daten |

**Szenarien (7 Kacheln, Profil B, Frontier):** 5 Chats/Kachel/Monat (35 Chats) = **4,26 $/Monat** ·
10 Chats (70 Chats) = **8,53 $/Monat** · 30 Chats (210 Chats) = **25,58 $/Monat**.
Zum Vergleich: **eine** Fachplaner-Stunde kostet 80–120 €. Die Modellwahl ist damit eine **Qualitäts-**, keine Kostenfrage.

**Tagesdurchsatz-Grenze der Gratis-Tarife:** 50 Requests/Tag ≈ **8 Chats (Profil B)** bzw. 16 Chats (Profil A) –
also rund *eine* Stadt mit einem aktiven Nutzer. Nach einmaligem 10-$-Guthaben: 1.000 Requests/Tag ≈ 166 Chats.

### 3.4 Effekt von Prompt-Caching

Bei bezahlten Anbietern kostet zwischengespeicherter Input ~10 % (Cache-Read), Schreiben ~125 % einmalig.
System-Prompt + Dateien sind über die Turns stabil → **10–25 % Gesamtersparnis**, auf dem stabilen Anteil bis ~70 %.
Die sieben Gratis-Modelle unterstützen **kein** implizites Caching (`supports_implicit_caching: false`) – bei
bezahlter Umstellung also Caching-fähige Anbieter wählen.

### 3.5 Sechs Hebel zur Token-Reduktion (ohne Qualitätsverlust)

| Hebel | Wirkung | Aufwand |
|---|---|---|
| Alte Turns zusammenfassen statt mitsenden („Rolling Summary") | −30 bis −50 % Input bei langen Chats | 2 Tage |
| System-Prompt-Kürzung (−20 % Zeichen bei gleicher Wirkung) | −15 % Input, senkt auch Latenz | 0,5 Tag |
| Datei-Kontext intelligent kürzen (Kopf + relevante Zeilen statt Bruchkürzung) | −20 bis −40 % bei großen Dateien | 1–2 Tage |
| Ergebnis statt Verlauf mitführen (Structured State) | −40 % ab dem 4. Turn | 3 Tage (mit Phase 1) |
| Modell-Routing (kleines Modell für Rückfragen, großes für Ergebnis) | −40 bis −60 % Output-Kosten | 2 Tage |
| Caching-fähige Anbieter bei bezahlter Nutzung | −10 bis −25 % | 0,5 Tag |

---

## 4. Was für Excel-, PDF- und Bild-Output nötig ist

### 4.1 Fundament: strukturierte Ausgabe

Heute liefert das Modell Markdown – gut fürs Auge, unbrauchbar für Dateien. Für Artefakte braucht es:
**JSON-Schema (structured output)** oder **Tool-Calling** mit Validierung (z. B. Pydantic), plus Fehlerpfad.
Verlässlich bei den Gratis-Modellen: `nvidia/nemotron-3-super-120b-a12b:free` und `apodex/apodex-1.1-mini:free`
(beide mit `structured_outputs`), Gemma nur mit `response_format` (JSON-Modus, keine Schema-Garantie).

Vorgeschlagener Datenfluss:

```
Datei/Text → LLM: Extraktion in JSON-Schema (Zahlen, Einheiten, Quellen)
           → Python: Validierung + Berechnung (Emissionsfaktoren, Umlaufzeiten, Kostenbänder)
           → LLM: Formulierung/Erzähltext auf Basis der berechneten Zahlen
           → Renderer: Excel (openpyxl) / PDF (HTML→PDF) / Diagramm (Plot) / SVG
           → Artefakt in DB + Download-Endpunkt /api/artifacts/{id}
```

Damit ist jede Zahl im Export **reproduzierbar** – Voraussetzung dafür, dass ein Amt das Ergebnis verwenden darf.

### 4.2 Excel

| Punkt | Umsetzung | Aufwand |
|---|---|---|
| Bibliothek | `openpyxl` ist **bereits Abhängigkeit** (für Upload-Extraktion) – kein neues Paket | – |
| Struktur | Blätter `Annahmen` (Faktoren, editierbar) · `Eingangsdaten` · `Bilanz` (mit **Zellformeln** auf die Annahmen) · `Maßnahmen` | 1 Tag |
| Qualität | Zahlen als Zahlen (nicht Text), Einheiten in Kopfzeilen, Zellkommentare mit Quelle/Annahme, Diagramm-Sheet | 1 Tag |
| Endpunkt | `POST /api/conversations/{id}/export/xlsx` → Datei-Download; Schema je Kachel (Bilanz, Maßnahmenkatalog) | 1 Tag |
| Wichtig | **Formeln statt fester Werte** – die Kommune muss Faktoren (z. B. 372 g CO₂/kWh) selbst ändern können | – |

### 4.3 PDF

| Weg | Vorteil | Nachteil | Aufwand |
|---|---|---|---|
| **A: Druck-CSS** (`@media print` + `window.print()`) | 0 Abhängigkeiten, sofort nutzbar, sieht nach Amt aus | Nutzer entscheidet über Speichern; keine Serverablage/Archivierung | **0,5 Tag** |
| **B: HTML → PDF mit WeasyPrint** | Layouts in HTML/CSS (Vorlagen pflegbar), Fußzeilen, Seitenzahlen, gutes Deutsch | Systembibliotheken (Pango/Cairo) im Docker nötig | 2 Tage |
| **C: ReportLab/fpdf2** | reines Python, kein Systempaket | Layoutarbeit in Code, Tabellenumbrüche mühsam | 3 Tage |

**Empfehlung:** A sofort (Deckend für Beschlussvorlagen), B sobald echte Vorlagen mit Briefkopf/Anlagenverzeichnis
gebraucht werden. Fahrplan im PDF sollte aus derselben JSON-Struktur kommen wie der Excel-Export.

### 4.4 Bild – drei verschiedene Dinge, die oft verwechselt werden

| Variante | Wofür | Umsetzung | Aufwand |
|---|---|---|---|
| **Diagramme** (Donut-Bilanz, Takt-Tafel, Kostenbalken) | Ergebnisse visualisieren | client-seitig (Chart.js/Canvas, kein Server) **oder** serverseitig matplotlib → PNG/SVG; Daten aus dem JSON-Schema | 1–2 Tage |
| **Fachliche Schemata** (Straßenquerschnitt, Knotenpunkt, Liniennetz) | Planungsdarstellung | **SVG per LLM als Text erzeugen** + Schema-Validierung, danach in der UI editierbar; deterministische Alternative: Bausteine im Code | 2–3 Tage |
| **Bild-Input** (Bestandsfotos, Luftbilder, Planausschnitte, Screenshots) | Bestandsanalyse | Anhang als Bild an die Vision-Modelle senden (`gemma-4-31b-it:free`, `gemma-4-26b-a4b-it:free`, `inkling:free`) – aktuell wird nur Text extrahiert, Bilder werden **verworfen** | 1–2 Tage |
| **Bildgenerierung** (Illustrationen) | Präsentationen, Bürgerkommunikation | über OpenRouter-Bildmodelle; für technische Inhalte nur eingeschränkt belastbar, Kosten pro Bild prüfen | 1 Tag + Kostenklärung |

**Karten/Geodaten:** statische Kartenkacheln + Overlay (SVG/Canvas) mit **Namensnennung (OSM)**; amtliche
Geodaten (ALKIS, DGM) nur mit Lizenz der Vermessungsverwaltung. Das ist ein Rechts-, kein Technikthema → eigene Entscheidung nötig.

### 4.5 Architekturempfehlung: „Rechnen im Code, formulieren im LLM"

Der wichtigste Qualitätssprung für SusMob – und die Voraussetzung für alle Exporte:

- **Rechner je Kachel** (reines Python, testbar): CO₂-Bilanz, Umlaufzeit/Taktbedarf, Kostenbänder, Priorisierungsmatrix, TCO-Vergleich.
- **LLM-Aufgaben:** Daten extrahieren (Schema), Annahmen benennen, Text formulieren, Prüffragen stellen, Quellen markieren.
- **Effekt:** keine halluzinierten Zahlen mehr, Export trivial, Token-Kosten sinken (kein „Kopfrechnen" über 34k Tokens Kontext).

Aufwand: 1 Tag je Rechenkachel (7 Kacheln), davon 3 mit echtem Rechenkern → **4–6 Tage**, hoher Nutzen.

---

## 5. Weitere sinnvolle Kacheln

Bewertungskriterien: klarer Dateninput · wiederkehrender Bedarf in jeder Kommune · prüfbares Ergebnis ·
Wiederverwendung bestehender Bausteine · politischer Anlass („Gremienvorlage nötig").

| # | Kachel | Ergebnis | Warum wertvoll | Aufwand |
|---|---|---|---|---|
| 1 | **Verkehrssicherheit & Schulwegsicherheit** | Unfallauswertung, Gefahrenstellen-Ranking, Maßnahmenliste | Höchste politische Priorität, harte Daten (Unfallstatistik), zahlt auf Fördermittel ein | 1 Tag + 1 Tag Unfall-CSV-Parser |
| 2 | **Ladeinfrastruktur-Konzept** | Standortanalyse, Bedarfsrechnung, Ausbaustufen, Fördermittel | Jede Kommune muss Ladeinfrastruktur planen (EU-AFID, Landesvorgaben); Verbrenner-Chats entfallen | 1 Tag |
| 3 | **Parkraum & Parkraumbewirtschaftung** | Parkraumbilanz, Tarif-/Bewirtschaftungsvorschlag, Beschlussvorlage | Wiederkehrendes Thema mit schnellen Einnahmen, politisch umkämpft → Argumentationsbedarf | 1 Tag |
| 4 | **Modal-Split & Mobilitätsbefragung (Monitoring)** | Auswertung Befragung/Zählung, Zielpfad, Indikatorenset | „Was wir nicht messen, können wir nicht steuern" – Voraussetzung für jede Erfolgsmeldung | 1,5 Tage |
| 5 | **Verkehrsversuch & Verkehrsberuhigung** | Anordnungsbaustein, Evaluationsplan, Kommunikationspaket | Viele Kommunen testen 30-km/h-Zonen/Zufahrtsbeschränkungen; Evaluation entscheidet über Dauerhaftigkeit | 1 Tag |
| 6 | **On-Demand-/Rufbus-Konzept** | Betriebsmodell, Kosten je Fahrgast, Angebotszeiten, Fördermittel | Ersatz für dünne ÖPNV-Takte im ländlichen Raum – die Kachel mit dem größten Neukunden-Nutzen | 1,5 Tage |
| 7 | Stadtbahn/SPNV-Anschluss & Bike+Ride | Zu-/Abbringer-Konzept, Kapazitätsbedarf, Abstellanlagen | Stationen erreichen nur mit Zuwegung ihre Wirkung | 1 Tag |
| 8 | Wirtschaftsverkehr & City-Logistik | Analyse Lieferverkehr, Mikro-Depots, Regelungen | Unvermeidliches Gegenstück zu Verkehrsberuhigung | 1,5 Tage |
| 9 | **Förder-Radar & Fristenkalender** | Programmübersicht, Passung, Fristen, Antragscheckliste | Querschnittskachel für alle anderen; bedient die größte Kommune-Angst | 1,5 Tage + Datenpflege |
| 10 | Kommunale E-Flotte & TCO-Vergleich | Total-Cost-of-Ownership-Rechner, Beschaffungsvorlage | Baut direkt auf CO₂-Bilanz auf; Rechner im Code statt LLM | 1 Tag |
| 11 | Luftreinhaltung & Lärmaktionsplan | Maßnahmenliste, rechtliche Fristen, Beteiligung | Gesetzliche Pflicht, oft mit Verkehrsmaßnahmen verknüpft | 1,5 Tage |
| 12 | Klimaanpassung & Hitzeaktionsplan (Mobilität) | Maßnahmen zu Hitze/Starkregen, Priorisierung | Zweiter großer Fördertopf, gleiche Zielgruppe | 1,5 Tage |

**Empfehlung Top 5:** Verkehrssicherheit/Schulweg · Ladeinfrastruktur · Parkraum · Monitoring/Modal Split · On-Demand.
Sie bedienen politische Dauerthemen, sind datenbasiert und teilen die Bausteine (Unfall-CSV-Parser, Rechner, Excel-/PDF-Export).

Jede Kachel braucht nach dem Muster der bestehenden: Prompt + Standardwerte + 1 Testfall + 1 Beispiel + Rechenkern
(= der Aufwand oben). Die „Kachel-Fabrik" ist damit gelöst – der Engpass ist **Prompt-Qualität und Prüfung**, nicht Code.

---

## 6. Plan

### Phase 0 – Betriebssicherheit & Messbarkeit (Woche 1 · 3–5 Tage)

- **Modell-Health-Check** je Kachel (Endpunktliste prüfen) + **Fallback-Kette** (3 Modelle) + 429-Backoff
- **Token-/Kostenmessung**: `usage` aus jedem OpenRouter-Response in eine Tabelle `llm_calls`
  (Kachel, Modell, Input-/Output-Tokens, Dauer, Kosten) + Admin-Auswertung → Schätzungen in diesem Dokument werden zu Messwerten
- **Audit-Log** (wer hat wann welches Ergebnis erzeugt) – Voraussetzung für Kommunen
- **Fehlerbilder**: Netzfehler, Limit, Schemafehler mit klarer Meldung
- *Akzeptanzkriterium:* Kein Kachel-Chat scheitert an Modellausfall; Kosten pro Chat sind auf 5 % genau messbar.

### Phase 1 – Ergebnis-Export (Woche 2–3 · 6–8 Tage)

- **Structured-Output-Schema je Kachel** + Pydantic-Validierung + Fehlerpfad (Reparaturprompt)
- **Artefakt-System**: `artifacts`-Tabelle, `POST /api/conversations/{id}/export/{format}`, Download-Liste in der UI
- **Excel** für CO₂-Bilanz und Maßnahmenkatalog (mit Formeln und Annahmen-Blatt)
- **PDF** zuerst als Druck-CSS, dann WeasyPrint mit Vorlage (Briefkopf, Anlagenverzeichnis)
- **Diagramme** client-seitig aus dem JSON-Schema (Bilanz-Donut, Kostenbalken, Takt-Tafel)
- *Akzeptanzkriterium:* Aus einem Chat entsteht in < 30 s eine .xlsx und ein PDF, deren Zahlen mit den Annahmen im Blatt verknüpft sind.

### Phase 2 – Rechenkerne & Qualitätssicherung (Woche 3–4 · 5–7 Tage)

- **Rechner im Code** für CO₂-Bilanz, ÖPNV-Umlauf, Kostenbänder/TCO (LLM formuliert nur)
- **Eval-Harness**: alle Testfälle automatisch gegen das jeweilige Modell, Bewertungsschema
  (Vollständigkeit, Annahmen markiert, keine erfundenen Zahlen, Format), Regression bei Prompt-Änderungen
- **Prompt-Ökonomie**: 20 % Kürzung mit Eval-Nachweis; Rolling Summary für lange Chats
- *Akzeptanzkriterium:* ≥ 90 % der Testfälle ohne erfundene Zahlen/Fristen; Token pro Ergebnisdokument −30 %.

### Phase 3 – Neue Kacheln (Woche 5–6 · 5–6 Tage)

- Top-3 zuerst: Verkehrssicherheit/Schulweg, Ladeinfrastruktur, Parkraum – je inkl. Rechenkern, Testfällen, Beispiel
- *Akzeptanzkriterium:* Jede neue Kachel hat Beispiel + Testfall und besteht das Eval-Set.

### Phase 4 – Produktionsreife (Woche 7–8 · 8–10 Tage)

- **Auth & Mandantenfähigkeit** (Kommune = Mandant), Rollen (Bearbeiter/Admin), Datenisolation
- **Datenschutz**: Anbieterwahl mit AVV, Free-Modelle für echte Daten sperrbar (Flag „nur Demo"), Löschkonzept, Auftragsverarbeitung dokumentiert
- **Betrieb**: Docker-Compose, Reverse Proxy + TLS, Backup/Restore, Retention, Monitoring, Betriebshandbuch
- *Akzeptanzkriterium:* Zwei Kommunen arbeiten getrennt; Datenexport/löschung ist auditierbar.

### Zeitliche Einordnung

| Woche | Inhalt | Ergebnis |
|---|---|---|
| 1 | Phase 0 | stabile Chats, echte Kostenmessung |
| 2–3 | Phase 1 | Excel/PDF/Diagramme aus dem Chat |
| 4 | Phase 2 | nachrechenbare Zahlen, Eval-Set |
| 5–6 | Phase 3 | 3 neue Kacheln |
| 7–8 | Phase 4 | mandantenfähig, DSGVO-Argumente, Deploy |

### Kennzahlen zum Steuern

| KPI | Ziel |
|---|---|
| Modellausfälle je 100 Chats | < 2 (durch Fallback: 0 sichtbare Fehler) |
| Kosten je qualifiziertem Chat (bezahlt) | < 0,15 $ |
| Token je Ergebnisdokument | −30 % gegenüber heute |
| Export-Zeit (xlsx/pdf) | < 30 s |
| Testfälle ohne erfundene Zahlen | ≥ 90 % |
| Beispiel-Unterhaltungen aktuell (mit echtem Modell erzeugt) | 7/7 |

---

## 7. Risiken

| Risiko | Auswirkung | Gegenmaßnahme |
|---|---|---|
| Gratis-Modell verschwindet / kein Endpunkt (heute bei Qwen passiert) | Kachel nicht nutzbar | Health-Check + Fallback-Kette (Phase 0) |
| Tageslimit 50 Requests | ~8 Chats/Tag für alle Kacheln | 10-$-Guthaben (1.000/Tag) oder bezahlter Tarif |
| Free-Provider trainiert mit Prompts | Datenschutzverstoß bei echten Kommunaldaten | Freigabe einholen oder bezahlter Tarif mit AVV (Phase 4) |
| Erfundene Fördersätze/Fristen | Haftung, Glaubwürdigkeitsverlust | „Quelle prüfen"-Pflicht, Förderdatenbank pflegen, Eval-Kriterium |
| Rechenfehler in Antworten | falsche Beschlussgrundlage | Rechner im Code (Phase 2) |
| Geodaten ohne Lizenz | Abmahnung | nur OSM mit Namensnennung oder Lizenz der Vermessungsverwaltung |
| Token-Kostenexplosion bei großen Dateien | Kosten, Latenz | Kontext-Diät, Zusammenfassungen, Obergrenzen je Chat |
| Prompt-Änderung verschlechtert Qualität unbemerkt | schleichender Qualitätsverlust | Eval-Harness als Regressionsschutz (Phase 2) |

---

## 8. Entscheidungen, die von dir gebraucht werden

1. **Datenschutz:** Dürfen Kommunaldaten (auch Demo-Daten) an Free-Provider gehen, die damit trainieren?
   Falls nein: bezahlter Tarif mit AVV oder Self-Hosting (Nemotron/Inkling sind offene Gewichte → lokal betreibbar).
2. **Zielgruppe:** Einzelkommune (Beratung) oder Mehr-Mandanten-Produkt? Bestimmt Phase 4 (Auth, Isolation).
3. **Budget:** Für welche Kacheln soll ein bezahltes Modell Standard sein (Empfehlung: Beschlussvorlagen, Förderanträge)?
4. **Export-Vorlagen:** Gibt es ein Corporate Design (Briefkopf, Schrift) für Vorlagen/PDF? Ohne Vorlage baue ich ein neutrales Layout.
5. **Geodaten:** Welche Quellen sind lizenziert verfügbar (OSM, ALKIS, eigene GIS-Daten)?
6. **Priorität:** Phase 0+1 (Betrieb + Export) wie empfohlen – oder zuerst mehrere neue Kacheln für die Demo?

---

## 9. Erste drei konkrete Schritte (wenn es morgen losgeht)

1. **`llm_calls`-Tabelle + Usage-Logging** (0,5 Tag) → Kosten dieser Analyse wandern von Schätzung zu Messwert.
2. **Health-Check + Fallback-Kette** (1 Tag) → kein Kachel-Chat fällt mehr aus; der Qwen-Fund wird systematisch abgesichert.
3. **JSON-Schema + Excel-Export für die CO₂-Bilanz** (2 Tage) → erstes echtes Artefakt, Blaupause für alle weiteren Formate.

---

*Hinweis zur Nachvollziehbarkeit: Zeichenmengen wurden direkt aus `data/susmob.db` gemessen, Modell-Eigenschaften
(Pricing, Kontext, Parameter, Uptime, Caching) aus der OpenRouter-API am 06.10.2026 abgefragt, Benchmark-Werte aus
öffentlichen Quellen (Artificial Analysis, MarkTechPost-Berichte) übernommen. Token-Zahlen sind Schätzungen mit
±25 % Unsicherheit; nach Umsetzung von Phase 0 sind exakte Werte verfügbar.*
