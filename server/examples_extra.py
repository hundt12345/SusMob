"""Beispiel-Unterhaltungen der neuen Kacheln (Plan-Abschnitt 5, Phase 3).

Ausgelagert aus ``server/examples.py``, damit die bestehende Datei übersichtlich
bleibt; das Format ist identisch (title, note, files, messages) und wird dort per
``EXAMPLES.update(EXAMPLES_NEU)`` eingebunden.
"""
from __future__ import annotations

EXAMPLES_NEU: dict[str, dict] = {
    # ---------------------------------------------- Verkehrssicherheit / Schulweg
    "verkehrssicherheit": {
        "title": "📘 Beispiel: Schulweg-Ranking aus Unfallliste",
        "note": "Zeigt den Ablauf: Datenbasis prüfen → Ranking mit Gewichtung schwerer Unfälle → Maßnahmen mit Kostenband und Zuständigkeit.",
        "files": [
            (
                "unfaelle_schulbezirk_2022_2025.csv",
                "ort;schwere;art;anzahl;verletzte;jahr\n"
                "Hauptstraße/Schulweg;schwer;Fußgänger;1;1;2022\n"
                "Hauptstraße/Schulweg;schwer;Fußgänger;1;1;2024\n"
                "Hauptstraße/Schulweg;leicht;Rad;3;0;2023\n"
                "Kreuzung Bahnhof;leicht;Rad;5;1;2022\n"
                "Kreuzung Bahnhof;schwer;Rad;1;1;2025\n"
                "Grundschule Nord;schwer;Schulweg;1;1;2023\n"
                "Bahnhofstraße Kita;leicht;Fußgänger;4;0;2024\n",
            ),
        ],
        "messages": [
            (
                "user",
                "Werte unsere Unfallliste für den Schulbezirk aus (Zeitraum 2022–2025, Quelle Polizei-Unfallstatistik). "
                "Erstelle das Gefahrenstellen-Ranking mit Gewichtung schwerer Unfälle und leite je Top-Stelle eine Maßnahme "
                "mit Kostenband und Zuständigkeit ab.",
            ),
            (
                "assistant",
                "## Datenbasis & Annahmen\n"
                "- Unfallliste der Kommune (Datei `unfaelle_schulbezirk_2022_2025.csv`), Zeitraum 2022–2025, **Angabe der Kommune** – "
                "amtliche Quelle ist die Unfallstatistik der Polizei; vor der Gremienvorlage abgleichen.\n"
                "- **Annahme** (Standardwert der Kachel, änderbar): schwere Unfälle mit Faktor 5 gewichtet, dazu 2 Punkte je verletzter Person.\n"
                "- Schulform-Fokus: Grundschule (Angabe der Kommune).\n\n"
                "## Gefahrenstellen-Ranking\n\n"
                "| Stelle | Unfälle | davon schwer | Verletzte | Punkte | Kategorie |\n"
                "|---|---|---|---|---|---|\n"
                "| Hauptstraße/Schulweg | 5 | 2 | 2 | 14,0 | Gefahrenstelle (vordringlich) |\n"
                "| Kreuzung Bahnhof | 6 | 1 | 2 | 14,0 | Gefahrenstelle (vordringlich) |\n"
                "| Grundschule Nord | 1 | 1 | 1 | 7,0 | Prüfstelle |\n"
                "| Bahnhofstraße Kita | 4 | 0 | 0 | 4,0 | Beobachtung |\n\n"
                "**Rechenweg:** Punkte = Anzahl × (Gewicht 5 bei schweren Unfällen, sonst 1) + 2 × Verletzte. "
                "Beispiel Hauptstraße: (2 × 5) + (3 × 1) + (2 × 2) = 17,0. Einordnung: ab 12 Punkten vordringlich, ab 6 Punkten Prüfstelle "
                "(**Annahme** = Schwellenwert der Kachel).\n\n"
                "## Maßnahmen je Top-Stelle\n\n"
                "| Stelle | Maßnahme | Priorität | Kosten (Band) | Zuständigkeit | Zeithorizont |\n"
                "|---|---|---|---|---|---|\n"
                "| Hauptstraße/Schulweg | Querungshilfe mit Mittellinsel, Sichtfelder freihalten, Hol-/Bringzone | hoch | 40–120 k€ | Straßenverkehrsbehörde + Bauhof | 6–18 Monate |\n"
                "| Kreuzung Bahnhof | Radverkehrsführung prüfen, vorgezogene Aufstellfläche, Tempo 30 im Knoten | hoch | 25–80 k€ | Straßenverkehrsbehörde | 6–12 Monate |\n"
                "| Grundschule Nord | Schulwegbegehung, Bordsteinabsenkung, Beschilderung | mittel | 5–15 k€ | Ordnungsamt + Polizei | 3–6 Monate |\n\n"
                "**Alle Kosten sind Richtwerte (Erfahrungswerte), keine Angebote** – vor Beschluss Kostenschätzung einholen.\n\n"
                "## Rechtliche Anordnungsbausteine\n"
                "- Tempo-30-Zone bzw. Tempo 30 vor Schulen/Kitas nach § 45 Abs. 1c StVO – Anordnung mit Begründung.\n"
                "- Querungshilfe/Mittellinsel ist eine straßenbauliche Maßnahme; Abstimmung mit dem Baulastträger.\n"
                "- Dauerhafte Kontrolle ist Personalthema: Die Kontrolldichte wirkt stärker als die Beschilderung allein.\n"
                "- **Wichtig:** Die Feststellung eines Unfallschwerpunkts trifft die Örtliche Unfalluntersuchung. "
                "Dieses Ranking ist die Vorbereitung dafür, nicht der Beschluss.\n\n"
                "## Förderung\n"
                "- Förderkulisse prüfen (u. a. Landesprogramme Schulwegsicherung, Radverkehrsförderung). "
                "**Programme und Fördersätze sind Annahmen und vor Antragstellung zu verifizieren.**\n\n"
                "## Nächste Schritte\n"
                "1. Unfallliste mit der Polizeiauswertung abgleichen und in der Unfallkommission vorlegen.\n"
                "2. Top-Stellen gemeinsam begehen (Schulleitung, Elternvertretung, Polizei, Ordnungsamt).\n"
                "3. Kostenschätzung und Förderfähigkeit für die vordringlichen Maßnahmen klären.\n\n"
                "> ⚠️ Annahmen: Unfalldaten der Kommune, Gewichtung 5, Schwellenwerte 6/12 Punkte, Kostenbänder als Erfahrungswerte, "
                "Förderprogramme ungeprüft.",
            ),
            (
                "user",
                "Wie argumentiere ich intern, wenn das Bauamt sagt, eine Mittellinsel halte den Verkehr auf?",
            ),
            (
                "assistant",
                "## Kurzargumentation (sachlich, prüffähig)\n\n"
                "**1. Sicherheit schlägt Reisezeit – mit belegter Stelle.**\n"
                "An der Hauptstraße/Schulweg sind im Auswertungszeitraum **5 Unfälle, davon 2 schwere, mit 2 verletzten Personen** "
                "dokumentiert (**Angabe der Kommune**). Ein schwerer Schulwegunfall kostet volkswirtschaftlich deutlich mehr als die "
                "Investition von 40–120 k€ in eine Querungshilfe (**Annahme**).\n\n"
                "**2. Eine Mittellinsel bündelt Querungen, sie verlangsamt nicht als Selbstzweck.**\n"
                "Statt vieler unkontrollierter Querungen entsteht **eine** klar erkennbare Querungsstelle. Vorher-Nachher-Untersuchungen "
                "zeigen in der Regel weniger Konfliktpunkte – **diese Wirkung ist für den konkreten Standort gesondert zu belegen**; "
                "Messwerte erfinde ich nicht.\n\n"
                "**3. Alternative Mischformen, falls der Einwand bestehen bleibt.**\n\n"
                "| Variante | Wirkung | Kostenband |\n"
                "|---|---|---|\n"
                "| Mittellinsel | Querung gebündelt, Rad-/Fußverkehr getrennt | 40–120 k€ |\n"
                "| Querungshilfe ohne Mittellinsel | Sichtbeziehung verbessert, geringerer Eingriff | 25–80 k€ |\n"
                "| Bordabsenkung + Beschilderung + Hol-/Bringzone | schnell, rechtlich einfach | 5–15 k€ |\n\n"
                "**4. Prüfbar statt behauptet.**\n"
                "Vorschlag: Vorher-Nachher-Messung (Geschwindigkeit V85, Konfliktzählung, Belegungsdaten) über 12 Monate. "
                "Ein Rückbau ist aufwendig (Größenordnung 10–15 % der Investition, **Annahme**, im Einzelfall zu beziffern).\n\n"
                "## Gegenargument und Entkräftung\n\n"
                "| Einwand | Entkräftung |\n"
                "|---|---|\n"
                "| „Wird zum Nadelöhr, mehr Stau.“ | V85 und Rückstaulänge messen und vorlegen; bei über ca. 10.000 Kfz/Tag andere Führung prüfen. |\n"
                "| „Zu teuer für eine Stelle.“ | 40–120 k€ ins Verhältnis zu den Folgekosten von Schulwegunfällen setzen (volkswirtschaftliche Sätze belegen). |\n"
                "| „Die Feuerwehr braucht die Breite.“ | Mittellinsel in Teilstücken queren lassen, Feuerwehr früh einbinden. |\n\n"
                "**Nächste Schritte:** (1) Bauamt und Feuerwehr in die Variantenwahl einbinden, (2) Verkehrsmenge und V85 als Zahlen vorlegen, "
                "(3) Schwerpunktfeststellung in der Unfallkommission beantragen.\n\n"
                "> ⚠️ Wirkungsaussagen und Rückbaukosten sind Erfahrungswerte bzw. Annahmen – vor der Gremienvorlage mit Quellen belegen.",
            ),
        ],
    },
    # ---------------------------------------------- Ladeinfrastruktur
    "ladeinfrastruktur": {
        "title": "📘 Beispiel: Ladebedarf 12.000 Pkw bis 2030",
        "note": "Zeigt die Bedarfsrechnung in Ausbaustufen: heute, Zwischenschritt und Zielbild, mit Leistung, Investitionsband und Prüfhinweisen.",
        "files": [
            (
                "pkwdaten_kommune.csv",
                "kenngroesse;wert\n"
                "pkw_bestand;12000\n"
                "e_anteil_heute;0,04\n"
                "ladepunkte_oeffentlich;14\n"
                "quote_laternenparker;0,55\n"
                "ziel_e_anteil_2030;0,22\n",
            ),
        ],
        "messages": [
            (
                "user",
                "Wir sind eine Kommune mit 12.000 Pkw, E-Anteil heute 4 %, 14 öffentliche Ladepunkte, 55 % der Pkw ohne eigene "
                "Lademöglichkeit. Ziel: 22 % E-Anteil 2030. Wie viele Ladepunkte brauchen wir und wie bauen wir aus?",
            ),
            (
                "assistant",
                "## Datenbasis & Annahmen\n"
                "- Pkw-Bestand 12.000, E-Anteil heute 4 %, Ziel 22 % (2030) – **Angaben der Kommune**.\n"
                "- **Annahme:** 55 % der E-Pkw haben keine eigene Lademöglichkeit (Laternenparker) und brauchen öffentliche Ladeinfrastruktur.\n"
                "- **Annahme:** Aufteilung 75 % AC (11–22 kW) und 25 % DC (Schnellladen); Richtwerte 1 AC-Punkt je 12 E-Pkw ohne eigene "
                "Lademöglichkeit, 1 DC-Punkt je 80 E-Pkw. Diese Richtwerte stammen aus Leitfäden und sind kommunal zu kalibrieren.\n"
                "- Gleichzeitigkeitsfaktor 35 % für den Leistungsbedarf.\n\n"
                "## Bedarf heute und im Zielbild\n\n"
                "| Jahr | E-Pkw | ohne eigene Lademöglichkeit | Ladepunkte AC | Ladepunkte DC | Ladepunkte gesamt | Leistungsbedarf |\n"
                "|---|---|---|---|---|---|---|\n"
                "| 2026 (4 %) | 480 | 264 | 17 | 1 | 18 | ca. 120 kW |\n"
                "| 2030 (22 %) | 2.640 | 1.452 | 91 | 5 | 96 | ca. 620 kW |\n\n"
                "**Rechenweg:** öffentlich benötigt = Pkw-Bestand × E-Anteil × Anteil ohne eigene Lademöglichkeit. "
                "AC = öffentlich × 0,75 ÷ 12; DC = öffentlich × 0,25 ÷ 80. "
                "Leistungsbedarf = (AC × 11 kW + DC × 150 kW) × Gleichzeitigkeitsfaktor.\n\n"
                "**Einordnung:** Bei 4 % E-Anteil ist der Bestand von 14 Ladepunkten fast ausreichend. Der eigentliche Ausbau liegt "
                "zwischen 2028 und 2030.\n\n"
                "## Ausbaustufen\n\n"
                "| Stufe | Zeitraum | Ladepunkte | Maßnahmen |\n"
                "|---|---|---|---|\n"
                "| Sofort | 0–12 Monate | +4 bis +6 (auf 18–20) | Auslastung je Standort erfassen, Lücken schließen, 2 Schnellladestandorte prüfen |\n"
                "| Ausbau | 2027–2028 | +40 (auf ca. 60) | Flächendeckung AC in Wohnquartieren, DC am Bahnhof und an der Hauptachse |\n"
                "| Zielbild | 2029–2030 | +36 (auf ca. 96) | Deckung der Zielquote, Anpassung alle 2 Jahre an reale Zulassungszahlen |\n\n"
                "**Investitionsband (Richtwerte):** AC 4–9 k€ je Ladepunkt, DC-Standort 50–120 k€, Netzanschluss gesondert. "
                "Für den Ausbau bis 2030 grob **0,5–1,4 Mio. €** – **Annahme, keine Angebote**.\n\n"
                "## Standortkriterien\n"
                "- **Wohnquartiere:** Laternenparken, Erreichbarkeit < 3 Gehminuten, Nachtbelegung, Konflikt mit Anwohnerparken prüfen.\n"
                "- **Schnellladen:** Hauptachsen, Bahnhof/P+R, Gewerbegebiete; Netzanschluss und Flächenverfügbarkeit entscheidend.\n"
                "- **Ausschluss:** Schulwegsituationen, Baumbestand (Wurzelschutz), Feuerwehrflächen, unklare Widmung.\n"
                "- Barrierefreie Bedienung, beleuchtete Standorte, Ad-hoc-Laden und Roaming nach Preisangabenverordnung.\n\n"
                "## Betriebsmodell und Recht\n"
                "- Betreiber: Stadtwerke, Dritter oder Kommune; Laufzeit, Vergabe und Wirtschaftlichkeit regeln.\n"
                "- Tarif: AC-Zeittarif, DC-Arbeitstarif, Blockiergebühr zur Freihaltung der Fläche.\n"
                "- Rechtlich: Stellplatzsatzung, Sondernutzung, Beschilderung (Parken nur während des Ladevorgangs).\n\n"
                "## Förderung\n"
                "- Förderkulisse wechselt jährlich (Bundesprogramme öffentliche Ladeinfrastruktur, Landesprogramme, teils Netzanschlusszuschüsse). "
                "**Programme, Fördersätze und Fristen sind hier Annahmen und vor Antragstellung zu prüfen.**\n\n"
                "## Nächste Schritte\n"
                "1. Auslastung je bestehendem Ladepunkt auswerten, Zulassungszahlen fortschreiben.\n"
                "2. Standortkonzept mit Netzanschlussprüfung beschließen.\n"
                "3. Betreibermodell entscheiden und Förderfähigkeit klären.\n\n"
                "> ⚠️ Die Bedarfsrechnung beruht auf Annahmen (75/25-Aufteilung, Richtwerte je Ladepunkt, 55 % Laternenparker). "
                "Mit eigenen Auslastungsdaten ist sie zu kalibrieren.",
            ),
            (
                "user",
                "Das ist viel Geld. Wie begründe ich den Ausbau gegenüber dem Kämmerer?",
            ),
            (
                "assistant",
                "## Argumentation gegenüber der Kämmerei\n\n"
                "**1. Ohne öffentliche Ladeinfrastruktur wird die beschlossene Zielquote nicht erreicht.**\n"
                "55 % der Pkw (**Annahme der Kachel**) haben keine eigene Lademöglichkeit. Ohne öffentliches Laden bleibt dieser Teil der "
                "Flotte faktisch beim Verbrenner – die Zielquote wäre nicht erfüllbar.\n\n"
                "**2. Der Großteil der Kosten ist nicht kommunal und fällt gestuft an.**\n"
                "Der Ausbau bis 2030 liegt grob bei 0,5–1,4 Mio. € (**Annahme**), verteilt über fünf Jahre. Je nach Programm ist ein "
                "Förderanteil üblich; die Kommune trägt vor allem Flächenbereitstellung, Planung und Netzanschlussvorleistung.\n\n"
                "**3. Einnahmen und Gegenwerte sind modellierbar, nicht behauptbar.**\n"
                "Ladegebühren und Konzessionsmodelle sind erlösfähig; die Wirtschaftlichkeit hängt an Auslastung und Tarif und ist als "
                "Modellrechnung vorzulegen.\n\n"
                "**4. Vergleichsrechnung statt Wunschliste.**\n\n"
                "| Position | Größenordnung | Belastbarkeit |\n"
                "|---|---|---|\n"
                "| Investition AC (ca. 87 Ladepunkte) | 350–780 k€ | Annahme (Richtwerte) |\n"
                "| Investition DC (5 Standorte) | 250–600 k€ | Annahme |\n"
                "| Netzanschluss | gesondert zu beziffern | offen – Netzbetreiber anfragen |\n"
                "| Nicht erreichte Zielquote | nicht seriös bezifferbar | als Lücke benennen, nicht schätzen |\n\n"
                "**5. Beschlussfähige Form: Stufenbeschluss.**\n"
                "Sofortstufe (4–6 Ladepunkte, niedriger fünfstelliger Betrag) jetzt beschließen, Ausbauentscheidung 2027 auf Basis "
                "gemessener Auslastung. Das begrenzt Risiko und macht Kosten planbar.\n\n"
                "**Nicht verwenden:** erfundene Umsatzrenditen, behauptete Fördertöpfe ohne Prüfvermerk, „E-Autos sind immer günstiger“.\n\n"
                "**Nächste Schritte:** (1) Auslastungsdaten der 14 Bestands-Ladepunkte vorlegen, (2) Netzanschlusskosten beim Netzbetreiber "
                "anfragen, (3) Förderfähigkeit mit Stand und Frist dokumentieren.\n\n"
                "> ⚠️ Alle Kosten- und Förderangaben sind Annahmen und nicht geprüft.",
            ),
        ],
    },
    # ---------------------------------------------- Parkraum
    "parkraum": {
        "title": "📘 Beispiel: Parkraum Innenstadt bewirtschaften",
        "note": "Zeigt Bilanz → Wirtschaftlichkeit → Bewirtschaftungsvorschlag → Beschlussvorlage in einem Durchlauf.",
        "files": [
            (
                "parkraumbestand.csv",
                "gebiet;parkstaende;auslastung_prozent\n"
                "Innenstadt;850;92\n"
                "Bahnhofsumfeld;210;88\n",
            ),
        ],
        "messages": [
            (
                "user",
                "Innenstadt: 850 öffentliche Parkstände, 92 % Auslastung zur Hauptzeit, heute kostenlos. Wir überlegen "
                "Bewirtschaftung von 300 Stellplätzen mit 1,00 €/h, Mo–Sa 9–18 Uhr. Erstelle Bilanz, Wirtschaftlichkeit und Vorschlag.",
            ),
            (
                "assistant",
                "## Datenbasis & Annahmen\n"
                "- 850 öffentliche Parkstände, 92 % Auslastung zur Hauptzeit, 300 Stellplätze zur Bewirtschaftung, Tarif 1,00 €/h "
                "Mo–Sa 9–18 Uhr – **Angaben der Kommune**.\n"
                "- **Annahmen (Erfahrungswerte):** Betriebskosten 260 € je Stellplatz und Jahr, Einnahmen 620 € je bewirtschaftetem "
                "Stellplatz und Jahr, Erstausstattung 1.200 € je Stellplatz.\n"
                "- Es liegt keine Zählung nach EAR/EAHV vor. Für die Gremienvorlage empfiehlt sich eine Zählung an drei Wochentagen "
                "mit je zwei Zeitfenstern.\n\n"
                "## Parkraumbilanz\n\n"
                "| Kennzahl | Wert | Bewertung |\n"
                "|---|---|---|\n"
                "| Parkstände | 850 | – |\n"
                "| Auslastung Hauptzeit | 92 % | **Handlungsbedarf** (Schwelle 85–90 %) |\n"
                "| Freie Parkstände Hauptzeit | ca. 68 | Suchverkehr wahrscheinlich |\n"
                "| Bewirtschaftung geplant | 300 | 35 % des Bestands |\n\n"
                "Ein Auslastungswert über 90 % bedeutet erfahrungsgemäß Suchverkehr – das ist das Hauptargument für Bewirtschaftung, "
                "nicht die Einnahme.\n\n"
                "## Wirtschaftlichkeit\n\n"
                "| Position | Wert |\n"
                "|---|---|\n"
                "| Einnahmen (300 × 620 €) | ca. 186.000 €/Jahr |\n"
                "| Betriebskosten bewirtschaftet (300 × 260 €) | ca. 78.000 €/Jahr |\n"
                "| Betriebskosten übrige Stellplätze (60 %) | ca. 86.000 €/Jahr |\n"
                "| Überschuss vor Abschreibung | ca. 22.000 €/Jahr |\n"
                "| Erstausstattung (300 × 1.200 €) | ca. 360.000 € |\n"
                "| Amortisation | ca. 16 Jahre |\n\n"
                "**Lesart:** Die Zahlen tragen sich, sind aber kein Selbstläufer. Empfindlichster Wert sind die Einnahmen je Stellplatz: "
                "Bei 450 € sinkt der Überschuss auf null. **Vor Beschluss rechnen, nicht schätzen.**\n\n"
                "## Bewirtschaftungsvorschlag\n"
                "- **Tarif:** 1,00 €/h mit 30-Minuten-Takt, Tageshöchstsatz 6,00 €; erste 30 Minuten in Randzeiten frei.\n"
                "- **Zeiten:** Mo–Sa 9–18 Uhr, Sonntag frei (Innenstadtbesuch nicht abschrecken).\n"
                "- **Ausnahmen:** Behindertenparkplätze, Ladeplätze (nur während des Ladevorgangs), Lieferzonen mit Zeitfenster, Bewohnerparken.\n"
                "- **Technik:** Parkscheinautomaten oder digitale Erfassung; bei Digitalisierung entfallen Automatenkosten, dafür sind "
                "Kontrolle und Datenhaltung zu regeln.\n"
                "- **Kommunikation:** vier Wochen Informationsphase, danach Kontrolle; Einzelhandel vorab informieren.\n\n"
                "## Rechtlicher Rahmen\n"
                "- Grundlage für Anordnung und Gebührenerhebung sind § 45 StVO und die landesrechtliche Parkgebührenregelung; "
                "**die konkrete Fassung ist vor Beschluss zu prüfen und im Vorlagentext zu zitieren** (hier nicht zitiert, da nicht verifiziert).\n"
                "- Bewohnerparken setzt die entsprechenden Voraussetzungen und ein abgegrenztes Gebiet voraus; Ausweise begrenzen.\n"
                "- Beschilderung und Kennzeichnung der Automaten sind Teil der Anordnung.\n\n"
                "## Argumente und Gegenargumente\n\n"
                "| Argument | Gegenargument | Entkräftung |\n"
                "|---|---|---|\n"
                "| 92 % Auslastung erzeugt Suchverkehr | „Dann bauen wir Parkplätze.“ | Ein neuer Parkplatz kostet 25–45 k€ je Stellplatz (Annahme) – erst lenken, dann bauen. |\n"
                "| Einnahmen decken den Betrieb | „Nur Abzocke.“ | Erste 30 Minuten und Sonntag frei; Einnahmen zweckgebunden kommunizieren. |\n"
                "| Bewohnerparken schützt Anwohner | „Der Handel verliert Kunden.“ | Kurzzeitparken bleibt möglich; Parkdauern belegen (Zählung). |\n\n"
                "## Beschlussvorlage (Entwurf)\n"
                "**Betreff:** Einführung der Parkraumbewirtschaftung in der Innenstadt (Teilbereich, 300 Stellplätze)\n"
                "**Sachstand:** 850 öffentliche Parkstände, Auslastung 92 % zur Hauptzeit (Angabe der Kommune), wachsender Suchverkehr, "
                "fehlende Lenkungswirkung gegenüber ÖPNV und Radverkehr.\n"
                "**Beschlussvorschlag:** Es wird beschlossen, für 300 Parkstände eine Bewirtschaftung mit 1,00 € je Stunde, Mo–Sa 9–18 Uhr, "
                "einzuführen. Die Verwaltung wird beauftragt, Tarif und Kontrolldichte zu evaluieren und nach zwölf Monaten zu berichten.\n"
                "**Finanzplan:** Erstausstattung ca. 360.000 € (Annahme), Einnahmen ca. 186.000 €/Jahr, laufende Kosten ca. 164.000 €/Jahr, "
                "Überschuss ca. 22.000 €/Jahr vor Abschreibung. [Platzhalter: Haushaltsstelle, Fördermittel]\n"
                "**Anlagenverzeichnis:** [1] Zählung Auslastung, [2] Tarifvergleich Nachbarkommunen, [3] Rechtsprüfung Parkgebührenregelung.\n"
                "**Prüfliste:** Rechtsgrundlage zitieren, Zählung belegen, Tarif vergleichen, Kontrollkosten beziffern, Beteiligung "
                "Einzelhandel und Behindertenbeauftragte.\n\n"
                "## Nächste Schritte\n"
                "1. Zählung der Auslastung (drei Wochentage, zwei Zeitfenster).\n"
                "2. Rechtsprüfung der Parkgebührenregelung und Abstimmung mit der Straßenverkehrsbehörde.\n"
                "3. Kontrollaufwand und Personalbedarf beziffern, dann in die Gremien.\n\n"
                "> ⚠️ Alle Kosten-, Einnahmen- und Fristangaben sind Annahmen und vor der Gremienvorlage zu prüfen.",
            ),
            (
                "user",
                "Wie hoch muss der Tarif sein, damit sich die Bewirtschaftung in 8 Jahren trägt?",
            ),
            (
                "assistant",
                "## Zielrechnung: Amortisation in 8 Jahren\n\n"
                "Ausgangslage (Annahmen aus dem Vorschlag): Erstausstattung 360.000 €, Betriebskosten der 300 bewirtschafteten Stellplätze "
                "78.000 €/Jahr, effektive Betriebskosten der übrigen 550 Stellplätze 51.600 €/Jahr.\n\n"
                "**Kosten in 8 Jahren:** 360.000 € + 8 × (78.000 € + 51.600 €) = **1.396.800 €**\n"
                "**Erforderlicher jährlicher Überschuss:** 1.396.800 € ÷ 8 = **174.600 €/Jahr**\n"
                "**Erforderliche Einnahmen:** 174.600 € + 78.000 € + 51.600 € = **304.200 €/Jahr**\n"
                "**Einnahmen je Stellplatz:** 304.200 € ÷ 300 = **1.014 €/Stellplatz und Jahr**\n\n"
                "Bei 9 h × 300 Tagen = 2.700 Öffnungsstunden ergibt sich als Mischkalkulation:\n\n"
                "| Tarif | Auslastung bewirtschaftete Plätze (**Annahme**) | Einnahmen/Jahr | Amortisation |\n"
                "|---|---|---|---|\n"
                "| 1,00 €/h | 23 % | 186.000 € | ca. 16 Jahre |\n"
                "| 1,50 €/h | 25 % | 304.000 € | ca. 8 Jahre |\n"
                "| 2,00 €/h | 18 % (Abwanderung) | 292.000 € | ca. 8,5 Jahre |\n\n"
                "**Befund:** Der Zielwert liegt bei etwa **1,50 €/h** – vorausgesetzt, die Belegung bleibt stabil. Bei 2,00 €/h rechnet "
                "sich der höhere Tarif nicht automatisch, weil ein Teil der Nachfrage ausweicht (**Annahme**, keine Messung).\n\n"
                "**Belastbare Prüfung:** Eine vierwöchige Zählung inklusive Parkdauer zeigt den Anteil Kurzzeit-/Langzeitparker. "
                "Erst danach ist der Tarif entscheidungsreif.\n\n"
                "**Alternative:** Digitalisierung senkt die Erstausstattung (Automaten entfallen). Bei ca. 200.000 € amortisiert sich "
                "1,00 €/h in ca. 11 Jahren, 1,50 €/h in ca. 5,5 Jahren.\n\n"
                "> ⚠️ Einnahmen, Auslastung und Elastizität sind Annahmen – das ist ein Prüfmodell, kein Ertragsnachweis.",
            ),
        ],
    },
}
