"""Beispiel-Unterhaltungen je Kachel ("Anschauungsmaterial").

Sie werden beim Start idempotent angelegt (feste IDs ``ex-<tile_id>``),
sind in der UI schreibgeschützt und lassen sich als eigene Unterhaltung
übernehmen. Über den Admin-Bereich kann jede Beispielantwort mit dem
echten, aktuell konfigurierten Modell der Kachel neu erzeugt werden
(``POST /api/admin/examples/regenerate``) – dafür ist Netz + API-Key nötig.

Aufbau je Kachel:
    title     Überschrift der Unterhaltung
    note      kurze Einordnung (wird als Hinweis-Banner angezeigt)
    files     Liste (Dateiname, Inhalt) – wird als echter Upload angelegt
    messages  Liste (role, inhalt) – role: "user" | "assistant"
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from pathlib import Path

from server import db
from server.examples_extra import EXAMPLES_NEU

EXAMPLES: dict[str, dict] = {
    # ------------------------------------------------------------ CO₂-Bilanz
    "co2-bilanz": {
        "title": "📘 Beispiel: Fuhrpark-Bilanz 2024",
        "note": "Zeigt den typischen Ablauf: Datenprüfung → Rückfragen → belastbare Bilanz mit Annahmen, Tabelle und Einsparpotenzialen.",
        "files": [
            (
                "fahrzeugbestand_2024.csv",
                "fahrzeug_id;art;kraftstoff;km_jahr;verbrauch;einsatz\n"
                "1-25;Pkw;Diesel;28000;6,8 l/100 km;Bauhof, Verwaltung, Außendienst\n"
                "26-29;Pkw;Elektro;22000;18,0 kWh/100 km;Bauhof, Verwaltung\n"
                "30-32;Bus (Stadtlinie);Diesel;85000;45,0 l/100 km;Linienbetrieb Stadtgebiet\n",
            )
        ],
        "messages": [
            (
                "user",
                "Wir wollen unsere CO₂-Bilanz für 2024 aufstellen. Der Fahrzeugbestand von Bauhof, "
                "Verwaltung und Stadtbusbetrieb hängt als CSV an. Bitte prüfe zuerst, ob die Daten für "
                "eine belastbare Bilanz reichen.",
            ),
            (
                "assistant",
                "**Kurzprüfung der Datenbasis** – die CSV enthält Fahrzeugart, Kraftstoff, Jahresfahrleistung "
                "und Verbrauch für 32 Fahrzeuge. Damit ist die Fahrzeugbilanz (Scope 1, direkte Emissionen) "
                "rechenbar. Vier Angaben fehlen mir noch:\n\n"
                "1. **Betrachtungsrahmen:** nur der kommunale Fuhrpark inkl. der 3 Stadtbusse – oder zusätzlich "
                "das gesamte Verkehrsaufkommen der Stadt (Scope 3)?\n"
                "2. **Strombezug der E-Fahrzeuge:** eigener Ökostromtarif oder Netzstrom? Ohne Angabe rechne ich "
                "mit dem UBA-Mix 2023 von 372 g CO₂/kWh (Annahme).\n"
                "3. **Vorkette (Well-to-Tank):** soll sie zusätzlich ausgewiesen werden?\n"
                "4. **Vergleichsjahr:** gibt es eine Vorjahresbilanz (2022/2023), gegen die ich stellen soll?\n\n"
                "Falls Sie mit meinen Annahmen einverstanden sind, schreiben Sie einfach „rechne so weit möglich“ – "
                "dann erstelle ich die Bilanz transparent mit gekennzeichneten Annahmen.",
            ),
            (
                "user",
                "Rahmen: nur kommunaler Fuhrpark inkl. der 3 Stadtbusse. Netzstrom mit 372 g CO₂/kWh. "
                "Vorkette bitte separat ausweisen. Vergleichsjahr haben wir nicht – rechne so weit möglich.",
            ),
            (
                "assistant",
                "## 1) Datenbasis & Annahmen\n\n"
                "- **Aktivitäten** aus `fahrzeugbestand_2024.csv`: 25 Diesel-Pkw × 28.000 km, 4 E-Pkw × 22.000 km, "
                "3 Dieselbusse × 85.000 km (Fahrleistungen als Jahreswerte, nicht geprüft – Angabe der Kommune).\n"
                "- **Verbräuche** aus der CSV: Diesel-Pkw 6,8 l/100 km, E-Pkw 18 kWh/100 km, Stadtbus 45 l/100 km.\n"
                "- **Faktoren** (Annahmen, Fachwerte): Diesel 2,68 kg CO₂/l; Stromnetz DE 372 g CO₂/kWh.\n"
                "- **Abgrenzung:** Scope 1 (direkte Emissionen) inkl. Stromverbrauch der E-Fahrzeuge; "
                "Besetzungsgrad nur für die Personenkilometer-Betrachtung.\n"
                "- **Nicht enthalten:** Kälte-/Klimamittel, Graue Energie der Fahrzeuge, Dienstreisen.\n\n"
                "## 2) Bilanz je Verkehrsträger\n\n"
                "| Verkehrsträger | Aktivitäten | Emissionsfaktor | t CO₂/a | Anteil % |\n"
                "| --- | --- | --- | --- | --- |\n"
                "| Pkw Diesel (25) | 700.000 km, 47.600 l | 2,68 kg/l | 127,6 | 28,9 |\n"
                "| Pkw Elektro (4) | 88.000 km, 15.840 kWh | 372 g/kWh | 5,9 | 1,3 |\n"
                "| Busse Diesel (3) | 255.000 km, 114.750 l | 2,68 kg/l | 307,5 | 69,7 |\n"
                "| **Summe** | | | **441,0** | **100,0** |\n\n"
                "**Rechenweg Busse:** 255.000 km × 45 l/100 km = 114.750 l × 2,68 kg/l = 307.530 kg.\n"
                "**Querkontrolle Pkw Diesel:** über den Flottenmittelwert 193 g/km ergäbe sich 135,1 t "
                "(+5,9 % gegenüber der verbrauchsbasierten Rechnung) – ich verwende den tatsächlichen Verbrauch, "
                "weil er die Kommune exakter abbildet.\n"
                "**Personenkilometer (Busse):** 307.530 kg ÷ (255.000 km × 38 Fahrgäste) = **31,7 g CO₂/Pkm** – "
                "typisches Niveau für Dieselstadtbusse.\n\n"
                "## 3) Vorkette (separat, Annahmen)\n\n"
                "- Diesel-Well-to-Tank: pauschal +20 % auf 435,1 t → ca. **87,0 t CO₂/a** (zu prüfen).\n"
                "- Stromvorkette: ca. +10 % auf 5,9 t → ca. **0,6 t CO₂/a**.\n"
                "- Bandbreite gesamt: **60–100 t CO₂/a** – bitte vor Veröffentlichung mit den UBA-Faktoren "
                "der jeweils gültigen Bilanzierungsmethode abgleichen.\n\n"
                "## 4) Top-Einsparpotenziale\n\n"
                "| Maßnahme | Einsparung t CO₂/a | Aufwand | Priorität |\n"
                "| --- | --- | --- | --- |\n"
                "| 3 Dieselbusse auf E-Busse (1,3 kWh/km, Netzstrom) | –184,2 (307,5 → 123,3) | hoch (Ladeinfrastruktur, Netzanschluss) | hoch |\n"
                "| Ökostromtarif für alle E-Fahrzeuge | –5,9 (bzw. zusätzlich rund –118 t ab E-Bus-Umstellung) | niedrig | hoch |\n"
                "| 3 Diesel-Pkw bei Neubeschaffung auf E umstellen | –9,7 | mittel (Beschaffungszyklus) | mittel |\n"
                "| Verbrauchscontrolling: Fahrerschulung, Reifendruck, Telemetrie (–5 %) | –6,4 | niedrig | mittel |\n\n"
                "## 5) Nächste Schritte\n\n"
                "1. Verbrauchswerte der drei Busse am Fahrtenbuch bestätigen (wirkungsstärkster Wert der Bilanz).\n"
                "2. Stromtarif der E-Fahrzeuge festlegen; bei Ökostrom entfällt der E-Anteil rechnerisch auf 0.\n"
                "3. Vorkette-Methodik fixieren (UBA-Faktoren, Bilanzjahr) und Bilanz nach Methodenkonsistenz "
                "für die kommenden Jahre fortschreiben.",
            ),
        ],
    },
    # ------------------------------------------------- Beschlussvorlagen
    "beschlussvorlagen": {
        "title": "📘 Beispiel: Beschlussvorlage E-Bus-Erwerb",
        "note": "Kompletter Vorlagenentwurf mit Beschlussvorschlag, Finanzplan und Prüfliste – Platzhalter als [ ] markiert.",
        "files": [],
        "messages": [
            (
                "user",
                "Wir brauchen die Beschlussvorlage für den Rat: Erwerb von 2 E-Bussen (je 450 k€) und "
                "Ladeinfrastruktur (150 k€). Stadt Musterstadt, NRW. Vorlagen-Nr. ist noch offen, Förderung "
                "über KIP mit 60 % (Annahme), Eigenanteil aus dem Haushalt. Alle Angaben sind da – bitte "
                "direkt den vollständigen Entwurf.",
            ),
            (
                "assistant",
                "**Annahmen & offene Punkte** (vor Einreichung prüfen – Stand muss vor Antragstellung auf der "
                "offiziellen Fördersuche verifiziert werden):\n\n"
                "- Förderquote 60 % über KIP als Annahme übernommen; Fördersätze, Fristen und Förderperiode "
                "sind Konditionen der Kommune und hier nicht geprüft.\n"
                "- Vorlagen-Nr., Fristen und Zuständigkeiten sind als `[Platzhalter]` gekennzeichnet.\n"
                "- Folgekosten (Strom, Wartung, Ladeinfrastruktur) sind Größenordnungen, keine Angebote.\n\n"
                "---\n\n"
                "# Beschlussvorlage\n\n"
                "**Betreff:** Beschaffung von zwei batterieelektrischen Linienbussen sowie Errichtung der "
                "zugehörigen Ladeinfrastruktur\n"
                "**Vorlagen-Nr.:** [2026/XXX]\n"
                "**Gremium:** Rat der Stadt Musterstadt\n"
                "**Federführung:** [Stadtwerke / Amt für Mobilität]\n\n"
                "## I. Stellungnahme\n\n"
                "**1. Sachstand**\n"
                "Der städtische Linienverkehr wird derzeit mit drei Dieselbussen bedient. Zwei Fahrzeuge haben "
                "nach Angabe des Betriebs [xxx.xxx km / Baujahr 2013] und verursachen neben steigenden "
                "Kraftstoffkosten zunehmende Instandhaltungsaufwände. Der Rat hat mit Beschluss [Nr./Datum] den "
                "Einstieg in die Elektrifizierung des Linienverkehrs beschlossen.\n\n"
                "**2. Anlass**\n"
                "Ersatzbeschaffung der zwei ältesten Fahrzeuge und Aufbau nutzbarer Ladeinfrastruktur, um "
                "Emissionen und Betriebskosten zu senken und die Klimaschutzziele der Stadt [Konzept/Beschluss] "
                "umzusetzen.\n\n"
                "**3. Ziele**\n"
                "- Reduktion der CO₂-Emissionen des Stadtbusverkehrs um rund [xx] t/a (Annahme: Umstellung von "
                "Diesel auf Netzstrom).\n"
                "- Senkung der Energiekosten je Fahrzeugkilometer (Annahme: 30–50 %).\n"
                "- Reduktion von Lärm- und Schadstoffbelastung im Innenstadtbereich.\n\n"
                "**4. Rechtlicher und organisatorischer Rahmen**\n"
                "Vergabe nach VgV/UVgO; Zuständigkeit des Rates nach § 41 GO NRW für die "
                "Investitionsentscheidung (Zuständigkeitsprüfung vorbehalten). Förderfähigkeit über das "
                "Kommunale Investitionsprogramm (KIP) sowie Landesprogramme [zu prüfen].\n\n"
                "**5. Alternativen**\n"
                "- Ersatz durch zwei Dieselbusse: geringere Anschaffungskosten, höhere Betriebskosten, "
                "Zielverfehlung.\n"
                "- Anmietung von E-Bussen: geringere Investition, höhere laufende Kosten, keine "
                "Förderfähigkeit nach Annahme.\n"
                "- Aufschub: Risiko steigender Preise und Fristversäumnis bei Förderprogrammen.\n\n"
                "## II. Beschlussvorschlag\n\n"
                "Der Rat beschließe:\n\n"
                "1. Die Verwaltung werde beauftragt, zwei batterieelektrische Linienbusse zu beschaffen und "
                "eine Ladeinfrastruktur mit [x] Ladepunkten an den Standorten [Betriebshof, Endhaltestelle] "
                "zu errichten.\n"
                "2. Für die Gesamtinvestition von 1.050.000 € (2 Busse à 450.000 €, Ladeinfrastruktur "
                "150.000 €) würden im Haushaltsjahr [2027] Mittel in Höhe von 420.000 € veranschlagt; "
                "630.000 € würden über die beantragte Förderung gedeckt.\n"
                "3. Die Verwaltung werde ermächtigt, den Förderantrag zu stellen und die erforderlichen "
                "Vergabeverfahren durchzuführen.\n\n"
                "## III. Finanzplan\n\n"
                "| Position | Betrag | Art |\n"
                "| --- | --- | --- |\n"
                "| 2 E-Busse | 900.000 € | Investition (einmalig) |\n"
                "| Ladeinfrastruktur | 150.000 € | Investition (einmalig) |\n"
                "| **Summe** | **1.050.000 €** | |\n"
                "| Förderung KIP (Annahme 60 %) | –630.000 € | Zuwendung |\n"
                "| **Eigenanteil** | **420.000 €** | Haushaltsmittel |\n\n"
                "| Folgekosten | je Jahr | Annahme |\n"
                "| --- | --- | --- |\n"
                "| Strom (2 Busse, 170.000 km, 1,3 kWh/km) | ca. 66.000 € | Strompreis 0,30 €/kWh |\n"
                "| Diesel im Vergleich | ca. 126.000 € | 76.500 l, 1,65 €/l |\n"
                "| **Minderkosten** | **ca. –60.000 €/a** | Preise sind Annahmen |\n"
                "| Wartung/Prüfung/Abgasnachbehandlung | ca. –8.000 €/a | kleinere Serviceumfänge |\n"
                "| Betrieb/Wartung Ladeinfrastruktur | ca. +5.000–8.000 €/a | Dienstleistervertrag |\n\n"
                "**Liquiditätswirkung:** 420.000 € Eigenanteil im Haushaltsjahr [2027]; ab Inbetriebnahme "
                "Entlastung von rund 60.000 €/a (Annahme, vorbehaltlich Strompreisentwicklung).\n\n"
                "## IV. Anlagenverzeichnis\n\n"
                "1. Antragsförmlicher Nachweis der Förderfähigkeit [Förderdatenbank-Ausdruck]\n"
                "2. Kostenaufstellung / Angebote [noch zu erstellen]\n"
                "3. Ladeinfrastruktur-Konzept mit Netzanschlussprüfung [xxx]\n"
                "4. Stellungnahme der Kämmerei\n"
                "5. Stellungnahme des Betriebsrats (Betriebsablauf, Ausbildung)\n\n"
                "---\n\n"
                "**Checkliste vor der Einreichung**\n"
                "1. Förderfähigkeit, Fördersatz und Frist im Programm aktuell prüfen.\n"
                "2. Zuständigkeit (Rat) und Vorlagen-Nr. abgleichen.\n"
                "3. Mittelveranschlagung mit dem Haushaltsplan [2027] abgleichen.\n"
                "4. Stellungnahmen (Kämmerei, Betrieb) einholen.\n"
                "5. Vergaberechtliche Vorprüfung durch die Vergabestelle bestätigen lassen.",
            ),
        ],
    },
    # ------------------------------------------------- Klimaschutzkonzept
    "klimaschutzkonzept": {
        "title": "📘 Beispiel: Klimaschutzkonzept Kleinstadt (15.000 EW)",
        "note": "Gliederung mit Inhalten/Datenbedarf plus die fünf wirkungsvollsten Maßnahmen für den ländlichen Kontext.",
        "files": [],
        "messages": [
            (
                "user",
                "Wir sind eine Kleinstadt mit 15.000 Einwohnern, ländlich geprägt, Kreislage. Es gibt ein "
                "Altkonzept von 2018 (Schwerpunkt Gebäude), einen Klimaneutralitätsbeschluss bis 2040 und seit "
                "2025 ein Klimaschutzmanagement mit 1,0 Stelle. Wir wollen fortschreiben. Skizziere bitte den "
                "Aufbau und nenne die fünf wirkungsvollsten Maßnahmen.",
            ),
            (
                "assistant",
                "**Annahmen (bitte ersetzen, sobald lokale Zahlen vorliegen):** Sektoranteile DE-Durchschnitt "
                "(Gebäude ca. 30 %, Verkehr ca. 22 %, Industrie ca. 17 %, Abfall ca. 4 %, Landwirtschaft ca. 9 %), "
                "Basisjahr 1990 (EU-Standard), Reduktionspfad 2030: –55 %, 2040: –88 % (Bund). Eigene "
                "Bilanzdaten aus dem Altkonzept 2018 gehen in die Fortschreibung ein, sind hier aber nicht bekannt.\n\n"
                "## 1) Ausgangslage\n\n"
                "- **Inhalte:** THG-Emissionen nach Sektoren, Entwicklung seit 1990 (bzw. seit Erstbilanz 2018), "
                "Bilanzierungsmethode und -grenzen, Datenlücken.\n"
                "- **Datenbedarf:** Endenergieverbrauch je Sektor (Gebäude nach Heizung/Strom, Verkehr nach "
                "Pkw/Nutzfahrzeugen/ÖPNV, Landwirtschaft nach Tierbestand/Fläche), Emissionsfaktoren, "
                "Einwohner- und Beschäftigtenentwicklung.\n"
                "- **Methodik:** Bilanzierung nach BISKO (endenergiebasiert, Territorialprinzip) – damit die "
                "Fortschreibung mit dem Altkonzept vergleichbar bleibt.\n"
                "- **Für Ihre Größe relevant:** Der ländliche Pkw-Anteil liegt typischerweise deutlich über dem "
                "Bundesschnitt; die Landwirtschaft ist – anders als in Städten – ein eigener Wirkungsbereich.\n\n"
                "## 2) Zielbild\n\n"
                "- Klimaneutralität 2040 (Ratsbeschluss) als Leitziel, Zwischenziele 2030/2035 je Sektor.\n"
                "- **Methodik:** Rückwärtsrechnung vom Zieljahr (CO₂-Budget-Ansatz) plus Sektorziele für "
                "Gebäude, Verkehr, Landwirtschaft und eigene Liegenschaften.\n"
                "- **Datenbedarf:** Zielbeschlüsse, Finanzrahmen, Personalressourcen.\n\n"
                "## 3) Maßnahmenstrategie je Sektor\n\n"
                "- **Gebäude:** Kommunale Wärmeplanung (Pflichtfristen nach Landesrecht), Sanierungsquote, "
                "Heizungstausch, Vorbildfunktion kommunaler Liegenschaften.\n"
                "- **Verkehr:** Ortsbus-/On-Demand-Angebot, Radnetz-Lückenschluss zu Schule und Ortskern, "
                "E-Ladeinfrastruktur, Pendler-Anreize.\n"
                "- **Landwirtschaft & Flächen:** Humusaufbau, PV-Freiflächen mit Doppelnutzung, Moorflächen.\n"
                "- **Eigene Verwaltung:** Energiecontrolling, Beschaffungsleitlinie, Personal.\n"
                "- **Methodik:** Wirkungsabschätzung als Band (t CO₂/a), Kosten je vermiedene Tonne als "
                "Priorisierungsgröße – als Schätzung kennzeichnen.\n\n"
                "## 4) Governance\n\n"
                "- Lenkungsausschuss (Verwaltungsspitze, Ratsfraktionen, Stadtwerke), Klimaschutzmanagement als "
                "Stabsstelle, Bürgerbeteiligung (Ortsbeiräte, Vereine, Landwirtschaftskammer).\n"
                "- **Datenbedarf:** Stellenplan, Beschlusslage, vorhandene Beteiligungsformate.\n\n"
                "## 5) Finanzierung & Förderung\n\n"
                "- Kommunalrichtlinie (Klimaschutzmanagement, Konzepte), KIP, Landesprogramme, "
                "Klimafonds; Eigenmittel und Personal.\n"
                "- **Hinweis:** Fördersätze und Fristen sind Konditionen der Zuwendungsgeber – vor Antragstellung "
                "in der offiziellen Förderdatenbank prüfen.\n\n"
                "## 6) Monitoring\n\n"
                "- Indikatoren: THG je Sektor, Sanierungsquote, Anteil Rad/ÖPNV am Modal Split, Anlagen-"
                "leistung PV, Heizungstauschquote. Fortschreibung alle 4 Jahre, Sachstandsbericht jährlich "
                "im Rat.\n\n"
                "## Die fünf wirkungsvollsten Maßnahmen für Ihren Kontext\n\n"
                "1. **Kommunale Wärmeplanung + Heizungstausch-Offensive.** Im ländlichen Raum dominiert der "
                "Wärmesektor die Emissionen, Wärmenetze für Ortskerne sind planungsrechtlich abgesichert und "
                "Voraussetzung für Fördermittel – höchster Hebel bei überschaubarer Steuerungsmöglichkeit der Kommune.\n"
                "2. **Energetische Sanierung von Schulen, Sporthallen und Verwaltungsgebäuden.** Die Kommune "
                "ist Eigentümerin, kann sofort handeln, wirkt als Vorbild und erzeugt sichtbare Einsparungen "
                "in ihrem eigenen Haushalt.\n"
                "3. **Ortsbus/On-Demand-Verkehr plus Radnetz-Lückenschluss.** In der Fläche entfällt der meiste "
                "Autoverkehr auf Fahrten zum Ortskern und zu Schule/Bahnhof; ein verlässliches Grundangebot und "
                "durchgängige Radwege verlagern genau diese Wege.\n"
                "4. **Ausbau der Photovoltaik inklusive Doppelnutzung von Flächen.** Je selbst erzeugter kWh "
                "sinkt der Emissionsfaktor des Stromverbrauchs in allen Sektoren gleichzeitig – wirkt also "
                "breit, ohne Verhaltensänderung zu erzwingen.\n"
                "5. **Landwirtschaft, Humusaufbau und Moorflächen.** Als ländliche Kommune haben Sie hier "
                "Einfluss, der Städten fehlt; zugleich ein Feld mit hoher Förderfähigkeit und ohne "
                "Zielkonflikt zum Nutzen der Betriebe.\n\n"
                "## Nächste drei Schritte\n\n"
                "1. Erstbilanz 2018 auf Konsistenz prüfen und Bilanz 2024/2025 mit gleicher Methodik rechnen.\n"
                "2. Sektorziele bis 2030 beschließen lassen (Ratsvorlage) und Haushaltsmittel für die "
                "Top-5-Maßnahmen einplanen.\n"
                "3. Förderzugänge für Wärmeplanung und Klimaschutzmanagement klären (Klimafonds, Kommunalrichtlinie).",
            ),
        ],
    },
    # ------------------------------------------------- Maßnahmenplanung
    "massnahmenplanung": {
        "title": "📘 Beispiel: Maßnahmenkatalog Mittelstadt (40.000 EW)",
        "note": "Priorisierter Katalog mit Kostenbändern, Phasenplanung und KPIs – zeigt, wie Kostenbänder statt Scheingenauigkeit aussehen.",
        "files": [],
        "messages": [
            (
                "user",
                "Mittelstadt, 40.000 Einwohner. Modal Split nach Haushaltsbefragung 2024: Rad 6 %, ÖPNV 12 %, "
                "Pkw 72 %, Fuß 10 %. Investives Budget 1,2 M€/Jahr, politische Priorität Klima. Es existieren "
                "ein Radverkehrskonzept (2019) und ein Klimaschutzkonzept. Bitte den priorisierten "
                "Maßnahmenkatalog erstellen.",
            ),
            (
                "assistant",
                "## 1) Kontext & Datenbasis\n\n"
                "- **Ausgangslage:** Pkw-Anteil 72 % (deutlich über dem Bundesdurchschnitt von rund 5x % – "
                "Einordnung, keine Bewertung), Rad 6 % (unter dem Durchschnitt vergleichbarer Städte).\n"
                "- **Ressourcen:** 1,2 M€/Jahr investiv – das ist die harte Nebenbedingung, deshalb sind alle "
                "Maßnahmen mit Kostenband und Phasenzuordnung versehen.\n"
                "- **Vorhandene Konzepte:** Radverkehrskonzept 2019 und Klimaschutzkonzept liefern Netzplanung "
                "und Maßnahmenlisten; hier wird konsolidiert und priorisiert, nicht neu geplant.\n"
                "- **Alle Kosten sind Annahmen** (Größenordnungsbänder aus der Praxis, keine Angebote).\n\n"
                "## 2) Maßnahmenkatalog\n\n"
                "| Maßnahme | Wirkung (CO₂/Sicherheit/Qualität) | Kosten (Band, gesamt) | Aufwand | Priorität |\n"
                "| --- | --- | --- | --- |\n"
                "| Geschützte Radwege auf 5 Hauptachsen (je 1 km) | hoch | 1,5–4,0 M€ | 3–10 Jahre, Planung/Förderung | hoch |\n"
                "| Radabstellanlagen an Schulen, Bahnhof, Busbahnhof (60 Plätze) | mittel | 18–90 k€ | 1 Jahr | hoch |\n"
                "| Fahrradstraßen im Quartier (2,5 km) | mittel | 75–200 k€ | 1–2 Jahre | hoch |\n"
                "| Busbeschleunigung an 6 Knoten (Vorrangschaltung) | mittel | 180–480 k€ | 1–3 Jahre | hoch |\n"
                "| Schulwegkonzept + Elterntaxi-Aktionsplan | mittel | 20–60 k€ | unter 1 Jahr | hoch |\n"
                "| 30-km/h-Zonen in 6 Quartieren | mittel | 30–180 k€ | unter 1 Jahr | hoch |\n"
                "| Monitoring: Modal-Split-Befragung, 4 Radzählstellen | – (Grundlage für alles) | 25–60 k€ | laufend | hoch |\n"
                "| Taktverstärkung Stadtbus HVZ 30 → 20 min | mittel–hoch | 150–400 k€/a (Betrieb) | 1–2 Jahre, Verkehrsvertrag | mittel |\n"
                "| Parkraumbewirtschaftung Innenstadt | mittel–hoch | 50–150 k€ Einführung + Personal | 1–2 Jahre | mittel |\n"
                "| P+R an zwei Stadtrandlagen (80 Plätze) | niedrig–mittel | 400–1.200 k€ | 3–10 Jahre | mittel |\n"
                "| Pendlerkampagne + Firmenticket-Umlage | mittel | 30–120 k€/a | 1–2 Jahre | mittel |\n"
                "| Mobilitätsstationen/Bikesharing (5 Standorte) | niedrig–mittel | 200–600 k€ | 3–10 Jahre | niedrig |\n\n"
                "**Priorisierung nach Kosten-Nutzen-Verhältnis:** Sofortmaßnahmen unter 200 k€ mit hoher "
                "Wirkung zuerst (Radabstellanlagen, Fahrradstraßen, 30-km/h-Zonen, Schulwegkonzept, Monitoring). "
                "Der geschützte Radweg auf den Hauptachsen ist der stärkste Hebel, sprengt aber allein das "
                "Jahresbudget – deshalb streckenweise und förderfinanziert.\n\n"
                "## 3) Phasenplanung\n\n"
                "**Sofort (unter 1 Jahr), rund 200–450 k€ aus dem laufenden Budget:**\n"
                "- Monitoring aufsetzen, Radabstellanlagen Standort 1–2, zwei Fahrradstraßen, "
                "zwei 30-km/h-Zonen, Schulwegkonzept.\n\n"
                "**Kurzfristig (1–3 Jahre), je 400–1.200 k€/a:**\n"
                "- Erste 2 km geschützter Radweg (Förderantrag im ersten Jahr), Busbeschleunigung an drei "
                "Knoten, Taktverstärkung HVZ, Parkraumbewirtschaftung einführen.\n\n"
                "**Mittelfristig (3–10 Jahre):**\n"
                "- Restliches Radhauptnetz, P+R-Anlagen, Mobilitätsstationen, Angebotsausweitung ÖPNV.\n\n"
                "## 4) KPIs & Monitoring\n\n"
                "| Maßnahme | KPI | Erhebung | Turnus |\n"
                "| --- | --- | --- | --- |\n"
                "| Radnetz | km geschützte Radinfrastruktur, Unfälle mit Radbeteiligung | Bau-/Unfallstatistik | jährlich |\n"
                "| ÖPNV | Fahrgastzahlen, Auslastung HVZ | Verkehrsverbund | jährlich |\n"
                "| 30-km/h-Zonen | Gefahrenlage, Akzeptanz | Unfallzahlen, Bürgerfeedback | 2 Jahre |\n"
                "| Gesamtwirkung | Modal Split | Befragung + Zählstellen | alle 3 Jahre |\n"
                "| Parkraum | Auslastung Innenstadt-Parkstände | Erhebung | jährlich |\n\n"
                "## 5) Nächste Schritte\n\n"
                "1. Sofortpaket (unter 1 Jahr) als Sammelbeschluss in den nächsten Haushalt einstellen – "
                "sofort sichtbare Ergebnisse sichern die politische Mehrheit.\n"
                "2. Für die ersten 2 km geschützter Radweg einen Förderantrag vorbereiten (KIP/Landesprogramm, "
                "Konditionen prüfen).\n"
                "3. Monitoring vor der ersten Maßnahme starten, damit die Wirkung belegbar wird.",
            ),
        ],
    },
    # ------------------------------------------------- Wegeplanung
    "wegeplanung": {
        "title": "📘 Beispiel: Radtrasse Wohngebiet Nord → Gesamtschule",
        "note": "Abschnittsweise Trassenplanung inkl. Trennungsform, Breite, Standard und dem offenen Budgetkonflikt.",
        "files": [
            (
                "abschnitte_nord_schule.csv",
                "abschnitt;laenge_m;avd_kfz_tag;lage;bestand\n"
                "A;1200;3500;innerorts, beidseitiges Parken;Schutzstreifen 1,5 m\n"
                "B;1500;2800;Ortsrand, Böschung nördlich;gemeinsamer Geh-/Radweg 2,0 m\n"
                "C;500;900;Schulbereich, Tempo-30-Zone;Fahrbahn ohne Markierung\n",
            )
        ],
        "messages": [
            (
                "user",
                "Plane die Radtrasse vom Wohngebiet Nord zur Gesamtschule. Gesamtlänge 3,2 km, drei Abschnitte "
                "mit Verkehrslasten (CSV). Budget 400 k€ (Invest), Fokus Schulweg, eine Bestandsaufnahme vor Ort "
                "liegt noch nicht vor.",
            ),
            (
                "assistant",
                "## 1) Datenbasis & Trassenkriterien\n\n"
                "- **Quelle:** `abschnitte_nord_schule.csv` (Längen, AVD, Lage, Bestand) – Angaben der Kommune, "
                "nicht verifiziert. Bestandsaufnahme steht aus.\n"
                "- **Zielgruppe:** Schulweg (Kinder/Jugendliche, Schulbeginn 7:30–8:00 Uhr). Daraus folgt der "
                "Vorrang für **getrennte Führung** und sichere Querungen statt schneller Mischverkehrslösungen.\n"
                "- **Gewichtung der Kriterien:** Sicherheit 40 % · Direktheit 25 % · Schulwegtauglichkeit 20 % · "
                "Kosten/Flächenverfügbarkeit 15 %.\n"
                "- **Kostenbänder sind Annahmen** (300–800 €/m getrennter Radweg, 80–200 €/m Radfahrstreifen, "
                "30–80 €/m Fahrradstraße, 20–80 k€ Einmündungsumbau).\n\n"
                "## 2) Trassenbeschreibung Abschnitt für Abschnitt\n\n"
                "| Abschnitt | Länge | Trennungsform | Breite | Standard | Kosten (Band) | Hinweis |\n"
                "| --- | --- | --- | --- | --- | --- | --- |\n"
                "| A (3.500 Kfz/d, innerorts) | 1.200 m | Radfahrstreifen, beidseitig | 2,0 m | StVO § 41 Nr. 5 / FAVR | 96–240 k€ | Parkstreifen entfällt abschnittsweise; Querung an 2 Grundstückszufahrten neu ordnen |\n"
                "| B (2.800 Kfz/d, Ortsrand) | 1.500 m | Getrennter Radweg, einseitig (Südseite) | 2,5 m | FAVR/DVFS | 450–1.200 k€ | Böschung nördlich: alternativ Radfahrstreifen auf der Fahrbahn (120–300 k€), Sicherheit geringer |\n"
                "| C (900 Kfz/d, Tempo 30) | 500 m | Fahrradstraße vor Schulbereich | – | StVO § 41 Nr. 16.1 | 15–40 k€ | Nur mit ganzheitlicher Beschilderung und Elterntaxi-Regelung wirksam |\n"
                "| Einmündungen/Knoten (3 Stück) | – | Querungshilfen, Vorrang Radverkehr | – | ERA/StVO | 60–240 k€ | Wichtigste Einzelmaßnahme für die Sicherheit im Schulverkehr |\n\n"
                "**Vorschlagsbeschilderung Abschnitt B (getrennt, einseitig):** Zeichen 240 (gemeinsamer Geh- und "
                "Radweg) wird wegen Breite 2,5 m nicht empfohlen; stattdessen Zeichen 237 (Radweg) mit "
                "Gegenverkehrsregelung – Ausführung final mit der Straßenverkehrsbehörde abstimmen.\n\n"
                "## 3) Gesamtkosten, Bauzeit, Risiken\n\n"
                "- **Kostenband gesamt:** 621–1.720 k€ (Mittel rund 1,1 M€) – **deutlich über dem Budget von "
                "400 k€.** Das ist der zentrale Konflikt und sollte offen in die Gremienkommunikation.\n"
                "- **Bauabschnitt 1 (A + C + ein Knoten):** 171–360 k€ – **innerhalb des Budgets** und sofort "
                "förderfähig, hoher Sicherheitsgewinn im Schulbereich.\n"
                "- **Bauabschnitt 2 (B):** Variante ohne Böschungseingriff (Radfahrstreifen) 120–300 k€ – "
                "Restbudget nach BA 1 reicht nur mit Förderung; getrennte Führung bleibt Zielvariante.\n"
                "- **Bauzeit:** BA 1 ca. 6–9 Monate, BA 2 ca. 9–12 Monate (Ausschreibung, Vollsperrungen "
                "abschnittsweise).\n"
                "- **Risiken:** ungeklärte Leitungen unter Abschnitt A (innerorts, Bordsteinanpassung), "
                "Baumfällungen im Böschungsbereich (B), Lärmschutzauflagen, Schulbetrieb während der Bauphase "
                "(Ferienfenster einplanen).\n\n"
                "## 4) Nächste Schritte\n\n"
                "1. Bestandsaufnahme und Leitungsauskunft für Abschnitt A und B beauftragen (Grundlage für die "
                "Kostenverschärfung).\n"
                "2. BA 1 planen und ausschreiben, Förderantrag mit Bezug zur Schulwegsicherheit stellen.\n"
                "3. Vor der Entscheidung zu Abschnitt B mit der Böschungseigentümerin und der "
                "Straßenverkehrsbehörde die Varianten abgleichen.",
            ),
        ],
    },
    # ------------------------------------------------- Argumentation
    "argumentation": {
        "title": "📘 Beispiel: Argumente zur E-Bus-Wirtschaftlichkeit",
        "note": "Argumentationskatalog mit Quellenhinweisen und Kurz-Briefing – der Bot kennzeichnet Zahlen, die zu prüfen sind.",
        "files": [],
        "messages": [
            (
                "user",
                "Die Kämmerin bezweifelt die Wirtschaftlichkeit unserer geplanten zwei E-Busse und will weiter "
                "Diesel nachkaufen. Gib mir vier Argumente mit Quellen und je ein typisches Gegenargument plus "
                "Entkräftung. Gegenüber: Kämmerin, Ton: sachlich-direkt.",
            ),
            (
                "assistant",
                "**Hinweis:** Die folgenden Zahlen sind Größenordnungen aus der Fachdebatte; alle mit "
                "„Quelle prüfen“ markierten Angaben bitte vor der Sitzung in der Originalquelle bestätigen – "
                "ich erfinde keine Quoten oder Studiensätze.\n\n"
                "## Argument 1: Die Gesamtkosten über die Lebensdauer, nicht der Kaufpreis, entscheiden\n\n"
                "- **Kernthese:** Bei 15 Jahren Nutzungsdauer und hoher Fahrleistung sind E-Busse trotz höherer "
                "Anschaffung wirtschaftlich, weil Energie und Wartung deutlich günstiger sind.\n"
                "- **Fakten:** Strom ist je gefahrenem Kilometer klar günstiger als Diesel (Richtwert: 60–75 % "
                "Minderkosten, „Quelle prüfen“); E-Antriebe entfallen Ölwechsel, "
                "Abgasnachbehandlung und AGR-Systeme; die Betriebserfahrung deutscher Verkehrsbetriebe zeigt "
                "stabilere Werkstattkosten („Quelle prüfen“).\n"
                "- **Typisches Gegenargument:** „Die Busse kosten 200–250 k€ mehr pro Stück.“\n"
                "- **Entkräftung:** Diese Mehrkosten verteilen sich auf 15 Jahre und werden durch niedrigere "
                "Energie- und Wartungskosten über die Laufleistung ausgeglichen – rechnen Sie bitte die "
                "Gesamtkosten je Kilometer, nicht den Kaufpreis.\n\n"
                "## Argument 2: Planungssicherheit bei den Kraftstoffkosten\n\n"
                "- **Kernthese:** Die Beschaffung von Dieselbussen zementiert ein Preis- und Regulierungsrisiko "
                "für die nächsten 15 Jahre.\n"
                "- **Fakten:** Die Mehrheit künftiger Betriebsjahre liegt nach den CO₂-Preispfaden der "
                "EU-Regulierung („Quelle prüfen“: EU-ETS2-Bepreisung, nationale Preisentwicklung); bereits "
                "heute sind die Kraftstoffkosten der zweiten Betriebsphase kaum kalkulierbar – als Risiko "
                "benennen, nicht als Prognose behaupten.\n"
                "- **Typisches Gegenargument:** „Wir wissen nicht, wie sich der Strompreis entwickelt.“\n"
                "- **Entkräftung:** Der Strompreis kann durch eigene PV-Erzeugung, Tarifverträge oder "
                "Ladezeitmanagement beeinflusst werden – der Dieselpreis nicht. Die Kommune tauscht einen "
                "nicht steuerbaren gegen einen teilweise steuerbaren Faktor.\n\n"
                "## Argument 3: Förderkulisse ist zeitlich befristet\n\n"
                "- **Kernthese:** Wer jetzt Diesel kauft, verzichtet dauerhaft auf die aktuelle Förderung für "
                "Elektromobilität im ÖPNV.\n"
                "- **Fakten:** Kommunale Verkehrsunternehmen erhalten Zuschläge über KIP, Landesprogramme und "
                "Klimafonds („Quelle prüfen: aktueller Fördersatz und Stichtag“); Fördersätze gelten jeweils "
                "für definierte Zeiträume.\n"
                "- **Typisches Gegenargument:** „Erst planen, später fördern lassen.“\n"
                "- **Entkräftung:** Bei einem Dieselbus ist für dieselbe Fahrleistung keine "
                "betriebskostensenkende Wirkung zu erzielen; die Beschaffung verschiebt das Problem nur um "
                "weitere 15 Jahre.\n\n"
                "## Argument 4: Risiken jenseits der Kosten (Personal, Akzeptanz, Stadtbild)\n\n"
                "- **Kernthese:** Die Entscheidung betrifft nicht nur den Finanzhaushalt, sondern die "
                "Zukunfts- und Belegschaftsfähigkeit des Betriebs.\n"
                "- **Fakten:** Fahrpersonal und Werkstatt suchen Arbeitgeber mit modernem Fahrzeugbestand "
                "(„Quelle prüfen: Fachkräftemangel-Studien zum ÖPNV“); Lärmminderung und Abgasfreiheit in der "
                "Innenstadt sind gerade auf stark belasteten Achsen unmittelbar wirksam („Quelle prüfen: "
                "UBA-Bewertung“).\n"
                "- **Typisches Gegenargument:** „Der Betrieb hat kein Personal für die Ladeinfrastruktur.“\n"
                "- **Entkräftung:** Ladeinfrastruktur wird in der Regel im Dienstleisterbetrieb zu festen "
                "Wartungspauschalen abgewickelt; klären Sie das vor der Beschaffung mit dem Betrieb und "
                "kalkulieren Sie es als Betriebskostenposition – dann ist es kein Personalrisiko, sondern "
                "eine Planungsfrage.\n\n"
                "## Kurz-Briefing für die Sitzung (max. 10 Zeilen)\n\n"
                "1. Wir vergleichen nicht Kaufpreise, sondern Gesamtkosten je Kilometer über 15 Jahre.\n"
                "2. Die Mehrinvestition liegt bei rund [x] € je Fahrzeug und wird durch Energie- und "
                "Wartungseinsparungen über die Laufleistung ausgeglichen (Rechnung wird vor Sitzung verteilt).\n"
                "3. Der Dieselpreis der nächsten 15 Jahre ist politisch und marktseitig unkalkulierbar, "
                "der Strompreis durch eigene Erzeugung und Ladezeitmanagement teilweise steuerbar.\n"
                "4. Förderfähigkeit jetzt: Programm, Satz und Stichtag sind [Stand: aktuelles Datum] zu "
                "prüfen – eine Entscheidung mit Fristbezug.\n"
                "5. Weitere Argumente liegen als Anlage bei: Personalgewinnung, Lärm- und Schadstoffentlastung "
                "in der Innenstadt.\n"
                "6. Angebot: Die Verwaltung rechnet die TCO-Vergleichsrechnung mit den tatsächlichen "
                "Fahrleistungen bis [Datum] vor – dann entscheiden wir auf derselben Datenbasis.",
            ),
        ],
    },
    # ------------------------------------------------- ÖPNV-Planung
    "opnv-planung": {
        "title": "📘 Beispiel: Landbus-Taktkonzept (12 km, 400 Fahrgäste/Tag)",
        "note": "Taktempfehlung, Umlaufrechnung, Fahrzeugbedarf und Kostenband – inklusive ehrlicher Einordnung, dass 400 Fahrgäste/Tag keinen 20-Minuten-Takt tragen.",
        "files": [],
        "messages": [
            (
                "user",
                "Landbus-Linie: 12 km, 400 Fahrgäste/Tag, 49-Sitzer, Durchschnittsgeschwindigkeit 22 km/h, "
                "14 Haltestellen. Wie soll der Takt in Haupt- und Nebenspitze aussehen und wie viele Fahrzeuge "
                "brauchen wir?",
            ),
            (
                "assistant",
                "## 1) Datenbasis & Annahmen\n\n"
                "- 400 Fahrgäste/Tag auf 12 km – das entspricht rund 33 Fahrgästen je km und Tag; "
                "**Annahme:** Verteilung mit deutlicher Spitze (etwa 45 % der Fahrten zwischen 6:00–8:00 und "
                "15:00–18:00 Uhr), der Rest gleichmäßig über den Tag.\n"
                "- 49 Plätze (Sitzplätze, Landbus-Näherung), Auslastungsschwelle 60 %.\n"
                "- Fahrzeit 12 km ÷ 22 km/h = **32,7 min je Richtung**, plus 14 Haltestellenaufenthalte sind "
                "in der Durchschnittsgeschwindigkeit bereits enthalten (Annahme).\n"
                "- Wendezeit 5 min je Endhaltestelle → **Umlaufzeit = 2 × 32,7 + 2 × 5 = 75,4 min**.\n\n"
                "## 2) Taktkonzept\n\n"
                "| Zeitfenster | Empfohlener Takt | Fahrtenpaare/Tag | Begründung |\n"
                "| --- | --- | --- | --- |"
                "\n| Hauptverkehrszeit (6–9, 15–18 Uhr) | 30 min | 12 | Merkbarer Umstieg auf den Bus, "
                "Anschluss an Bahn/Stadtbus |\n"
                "| Nebenverkehrszeit (9–15, 18–20 Uhr) | 60 min | 8 | Versorgungsniveau ländlich (30–60 min) |\n"
                "| Schwachlast (20–23 Uhr, Wochenende) | 120 min | 4 | Grundangebot, alternativ On-Demand/Anrufsammeltaxi |\n"
                "| **Summe** | | **24 Fahrtenpaare/Tag** | |\n\n"
                "**Ehrliche Einordnung:** Bei 400 Fahrgästen/Tag ergeben 48 Einzelfahrten im Schnitt rund "
                "**8–9 Fahrgäste je Fahrt** – das liegt weit unter der Auslastungsschwelle von 60 %. Ein "
                "durchgehender 20-Minuten-Takt wäre bei dieser Nachfrage betriebswirtschaftlich nicht "
                "vertretbar. Empfehlung daher: **Grundtakt 60 min mit Verdichtung auf 30 min in den Spitzen** – "
                "das ist ein Angebot, das die Nachfrage erfahrungsgemäß selbst erhöht (Induzierung als Annahme "
                "markiert).\n\n"
                "## 3) Fahrzeugbedarf\n\n"
                "- 30-Minuten-Takt: Umlaufzeit 75,4 min ÷ 30 min = 2,5 → **3 Fahrzeuge** (Reserve für "
                "Ausfall/Service inklusive).\n"
                "- 60-Minuten-Takt: 75,4 ÷ 60 = 1,26 → **2 Fahrzeuge** (unter Annahme einer Kurzwende im "
                "Betriebshof; sonst 3).\n"
                "- Praxisempfehlung: **2 Fahrzeuge im Grundtakt, das dritte Fahrzeug als Spitzen-/Reservebus.** "
                "Bei einer Verdichtung in den Spitzen ist der dritte Bus gebunden – Ausfallreserve muss "
                "vertraglich geregelt werden.\n\n"
                "## 4) Kosten & Förderung\n\n"
                "| Position | Größenordnung | Annahme |\n"
                "| --- | --- | --- |\n"
                "| Betriebsleistung | ca. 24 × 12 × 2 = 576 km/Tag, ca. 175.000 km/a | 300 Betriebstage |\n"
                "| Betriebskosten je km | 1,80–2,60 € | Personal, Energie, Wartung, Betriebshof |\n"
                "| **Subventionsbedarf** | ca. **315–455 k€/a** | vorbehaltlich erzielbarer Fahrerlöse |\n"
                "| E-Bus statt Dieselbus | 350–500 k€ vs. 200–300 k€ | einmalige Mehrinvestition |\n"
                "| Förderkulisse | KIP, Landesprogramme, ÖPNV-Richtlinien | Förderfähigkeit und Sätze prüfen |\n\n"
                "**Wirtschaftlichkeit:** Fahrgäste je km im Bestand wäre zu prüfen; ohne Tariferlösdaten ist "
                "der Deckungsgrad hier nicht seriös bezifferbar – bitte Tarifverbund-Prognose nachliefern.\n\n"
                "## 5) Risiken\n\n"
                "- **Fahrpersonal:** Fachkräftemangel kann den Spitzenfahrplan unmöglich machen – Schichtplanung "
                "früh mit dem Betrieb abstimmen.\n"
                "- **Fahrzeugverfügbarkeit:** bei nur 3 Fahrzeugen ist ein Ausfall sofort taktrelevant.\n"
                "- **Anschlussqualität:** Umstiege zur Bahn nur bei abgestimmten Übergangszeiten (5–10 min "
                "Übergang) attraktiv.\n\n"
                "## 6) Nächste Schritte\n\n"
                "1. Fahrgastzählung vier Wochen lang (je Haltestelle und Fahrt) – Basis für die Verdichtung.\n"
                "2. Fahrplanentwurf mit dem Tarifverbund rechnen und Anschlüsse zur Bahn prüfen.\n"
                "3. Förderzugang und Tariferlösprognose klären, bevor der Takt beschlossen wird.",
            ),
        ],
    },
}




# Neue Kacheln (Plan Phase 3) – ausgelagert, damit diese Datei übersichtlich bleibt
EXAMPLES.update(EXAMPLES_NEU)


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")


def seed_examples(upload_dir: Path) -> list[str]:
    """Legt fehlende Beispiele an (idempotent) und gibt die Kachel-IDs zurück."""
    created: list[str] = []
    for tid, ex in EXAMPLES.items():
        cid = f"ex-{tid}"
        if db.query1("SELECT id FROM conversations WHERE id=?", (cid,)):
            continue
        ts = _now()
        db.exec(
            "INSERT INTO conversations (id, tile_id, title, created_at, updated_at, is_example) "
            "VALUES (?,?,?,?,?,1)",
            (cid, tid, ex["title"], ts, ts),
        )
        for role, content in ex["messages"]:
            db.exec(
                "INSERT INTO messages (conversation_id, role, content, created_at) VALUES (?,?,?,?)",
                (cid, role, content, ts),
            )
        ex_dir = Path(upload_dir) / "examples"
        for filename, content in ex.get("files", []):
            fid = uuid.uuid4().hex
            ex_dir.mkdir(parents=True, exist_ok=True)
            stored = ex_dir / f"{fid}_{filename}"
            stored.write_text(content, encoding="utf-8")
            db.exec(
                "INSERT INTO files (id, conversation_id, tile_id, filename, size, stored_path, "
                "extracted_chars, extracted_text, created_at) VALUES (?,?,?,?,?,?,?,?,?)",
                (fid, cid, tid, filename, len(content.encode("utf-8")), str(stored), len(content), content, ts),
            )
        created.append(tid)
    return created


def replace_messages(cid: str, messages: list[tuple[str, str]]) -> None:
    """Ersetzt alle Nachrichten einer Beispiel-Unterhaltung (für die Neuerzeugung)."""
    ts = _now()
    db.exec("DELETE FROM messages WHERE conversation_id=?", (cid,))
    for role, content in messages:
        db.exec(
            "INSERT INTO messages (conversation_id, role, content, created_at) VALUES (?,?,?,?)",
            (cid, role, content, ts),
        )
    db.exec("UPDATE conversations SET updated_at=? WHERE id=?", (ts, cid))
