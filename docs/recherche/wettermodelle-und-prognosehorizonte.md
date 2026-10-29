# Wettermodelle für PV-Prognosen und Speicherentscheidungen

Recherche: 28.10.2026. Codeabgleich: Adaptive Solar 0.2.14, Repositorystand
`b99d86c`. **Ergänzter Entwicklungsstand: Originalarchiv, Modell-/Ensembleaufnahme
und Offline-Replay implementiert; noch nicht produktiv aktiviert.** Neue
produktive Gewichtung und Speichersteuerung stehen aus. Die Empfehlung gilt
für Deutschland/Mitteleuropa; regionale Modellgebiete sind am tatsächlichen
Standort gesondert zu prüfen. Es liegt kein lokaler Genauigkeitsvergleich vor.

## Inhalt

- [1. Empfehlung und Evidenz](#1-empfehlung-und-evidenz)
- [2. Geeignete Modelle](#2-geeignete-modelle)
- [3. Abdeckung und Modellwechsel](#3-abdeckung-und-modellwechsel)
- [4. Archivumfang und Abrufe](#4-archivumfang-und-abrufe)
- [5. Bewertung für Akkuentscheidungen](#5-bewertung-für-akkuentscheidungen)
- [6. Umsetzung und Abnahme](#6-umsetzung-und-abnahme)

## 1. Empfehlung und Evidenz

Die nächsten 48 Stunden sind die primäre Prüfaufgabe: verbleibender Tagesertrag,
nächster Solarzyklus und die Energie bis zur folgenden Nacht. Kurze regionale
Modelle sollen innerhalb ihrer verfügbaren Intervalle mitwirken. Ihr Ende darf
weder die gesamte Prognose abschneiden noch durch fortgeschriebene Werte
kaschiert werden. Globale Modelle werden gleichzeitig erfasst und übernehmen
auch schon vor Ablauf der Regionalmodelle eine Vergleichs- und Rückfallfunktion.

Empfohlener Grundbestand für das Archiv: **ICON-D2, ICON-EU, ECMWF IFS HRES 9 km
und GFS**, ergänzt um **DMI HARMONIE** bei örtlicher Abdeckung. Weitere regionale
Modelle sind begrenzte Vergleichskandidaten. **Echte Wetterensembles gehören ab
Aufnahmestart dazu: ICON-D2-EPS und IFS-ENS.** Die ausdrückliche Anforderung vom
28.10.2026 ist eine Einschätzung von Ertragswahrscheinlichkeiten.
`best_match` bleibt eine separat
aufgenommene Referenz und bewahrt gegebenenfalls den produktiv verwendeten
Wetterpfad. Das ist eine Auswahl nach Datenangebot und Vergleichsnutzen,
keine festgestellte Genauigkeitsrangliste.

Eine 2026 veröffentlichte Studie berichtet im Abstract für 27 deutsche
Messstationen, Sommer 2024 und Vorläufe unter 24 Stunden die beste Genauigkeit
für ICON-D2-EPS; IFS-ENS und MOGREPS-G waren hinsichtlich Unsicherheit besonders
verlässlich. Das stützt einen Versuch mit regionalen Modellen, belegt aber
weder die Überlegenheit des deterministischen ICON-D2 noch die Leistung im
Winter oder bei 24–48 Stunden. Grundlage ist der öffentlich zugängliche
[Abstract der Studie](https://www.sciencedirect.com/science/article/pii/S0038092X26004342),
nicht eine Prüfung des Volltexts.

Der [vorangegangene Konferenzbeitrag](https://meetingorganizer.copernicus.org/EMS2025/EMS2025-420.html)
zeigt außerdem zu enge Ensembleverteilungen. Kleine Gitterabstände und viele
Mitglieder ersetzen deshalb keine Prüfung an qualifizierten lokalen Messungen.

## 2. Geeignete Modelle

Horizonte sind dokumentierte Produktobergrenzen. Verbleibende Abdeckung hängt
vom Modelllauf, Bereitstellungsverzug, Standort, Parameter und tatsächlicher
Antwort ab. Ein API-Array mit 168 Zeitstempeln beweist keine 168 gültigen Stunden.
Rasterangaben beschreiben das angebotene Produkt, nicht die Genauigkeit am Dach.

| Modell / Kennung der Forecast-API | Raster; Aktualisierung | Dokumentierter Horizont | Vorgesehene Rolle und Quelle |
| --- | --- | --- | --- |
| ICON-D2 / `icon_d2` | etwa 2 km; 3-stündlich | bis 48 h | Regionaler Hauptkandidat für die kurze Frist; [DWD-Angebot](https://open-meteo.com/en/docs/dwd-api) |
| ECMWF IFS HRES / `ecmwf_ifs` | 9 km; 6-stündlich | bis 15 Tage | Globaler Vergleich ab Stunde 0, langfristige Fortsetzung; [ECMWF-Angebot](https://open-meteo.com/en/docs/ecmwf-api) |
| ICON-EU / `icon_eu` | etwa 7 km; 3-stündlich | bis 5 Tage | Regionaler Vergleich und Fortsetzung nach D2; [DWD-Angebot](https://open-meteo.com/en/docs/dwd-api) |
| GFS / `gfs_global` | etwa 13 km; 6-stündlich | bis 16 Tage | Andere Modellfamilie als Vergleich und Rückfall; [GFS-Angebot](https://open-meteo.com/en/docs/gfs-api) |
| DMI HARMONIE / `dmi_harmonie_arome_europe` | 2 km; 3-stündlich | bis 60 h | Zweiter regionaler Kandidat bei Gebietsabdeckung; [DMI-Angebot](https://open-meteo.com/en/docs/dmi-api) |
| KNMI HARMONIE / `knmi_harmonie_arome_europe` bzw. `knmi_harmonie_arome_netherlands` | 5,5 bzw. 2 km; stündlich | bis 60 h | Zusatzversuch; feines Gebiet insbesondere Niederlande/Belgien und angrenzende Bereiche; [KNMI-Angebot](https://open-meteo.com/en/docs/knmi-api) |
| AROME France / `meteofrance_arome_france` | etwa 2,5 km; 3-stündlich | etwa 2 Tage | Zusatzversuch bei Gebietsabdeckung; [Météo-France-Angebot](https://open-meteo.com/en/docs/meteofrance-api) |

Für Standorte im passenden Gebiet kommen zusätzlich MeteoSwiss ICON-CH1
(1 km, 33 h) und CH2 (2 km, 120 h) infrage. Diese sind insbesondere für einen
regionalen Vergleich im Alpenraum interessant, aber keine pauschale Empfehlung
für jeden deutschen Standort. [MeteoSwiss-Angebot](https://open-meteo.com/en/docs/meteoswiss-api)

Für die PV-Umrechnung ist auch die Herkunft der Strahlung wichtig: ICON liefert
direkte und diffuse Komponenten; beim IFS HRES sind globale und direkte
Strahlung verfügbar. IFS 0,25° sowie AROME France und KNMI benötigen für die
Aufteilung der Globalstrahlung eine zusätzliche Providerableitung. GFS liefert
globale und diffuse Strahlung; DMI bietet native Direktstrahlung. Die jeweiligen
Abschnitte „Native/Derived Variables“ der oben verlinkten Anbieterunterlagen
beschreiben diese Unterschiede. Im Archiv sind Providerableitungen von eigenen
Berechnungen zu unterscheiden; eine API-DNI-Reihe ist nicht automatisch ein
direkt vom Wettermodell ausgegebenes Feld.

IFS HRES ist für den ersten Vergleich dem ebenfalls verfügbaren `ecmwf_ifs025`
vorzuziehen: Es liefert in den ersten 90 Stunden native Stundenwerte; die
0,25°-Ausgabe hat gröbere Zeitstufen. Das ist eine begründete Auswahl des
Datenprodukts, kein nachgewiesener lokaler Prognosegewinn. AIFS mit seinen
sechsstündlichen Ausgaben ist ein späterer Zusatzversuch.
[ECMWF-Produktvergleich](https://open-meteo.com/en/docs/ecmwf-api)

`best_match`, `icon_seamless` und einzelne ICON-Modelle können überlappende
Information enthalten. Ebenso sind mehrere ICON-Varianten sowie DMI/KNMI
statistisch nicht unabhängig. Diese Pfade dürfen nicht allein durch ihre Zahl
mehr Gewicht erhalten. Einzelmodelle separat archivieren; automatische
Providerkombinationen als eigene Referenz kennzeichnen.
[Best-Match-Beschreibung](https://open-meteo.com/en/docs#best-match-model-selection)

### 2.1 Echte Ensembles als Teil des Grundbestands

Mehrere deterministische Modelle und die Mitglieder eines Wetterensembles sind
unterschiedliche Datenarten. Beide werden getrennt erhalten. Für Ensembleabrufe
wird ein eigener Adapter benötigt; die nachstehenden Kennungen beziehen sich
auf die Ensemble-API und sind keine Anleitung, sie ungeprüft in die heutige
HA-Modellauswahl einzutragen.

| Produkt / Ensemble-API-Kennung | Mitglieder; Horizont | Verwendung |
| --- | --- | --- |
| ICON-D2-EPS / `dwd_icon_d2_eps` | 20; bis 48 h, 3-stündliche Aktualisierung | Regionale Ertragsverteilung für vollständig abgedeckte kurze Zeitfenster |
| IFS Europe / `ecmwf_ifs_europe_ensemble` | 51; bis 15 Tage, 9 km | Ergänzung ab Stunde 0 und vollständige längere Entscheidungsfenster; verfügbare Läufe gesondert prüfen |
| IFS 0,25° / `ecmwf_ifs025_ensemble` | 51; bis 15 Tage, 6-stündliche Aktualisierung | Rückfall-/Vergleichsprodukt, falls die europäische Ausgabe nicht ausreichend verfügbar ist |

Die [Ensemble-Dokumentation](https://open-meteo.com/en/docs/ensemble-api)
führt für die europäische 9-km-Ausgabe derzeit nur 00/06-UTC-Läufe auf.
IFS-Produktauflösung und Aktualität sind deshalb gemeinsam zu bewerten.
Die [offizielle Kennungsliste](https://github.com/open-meteo/open-meteo-website/blob/main/src/routes/en/docs/ensemble-api/options.ts)
und der tatsächlich nutzbare Endpoint müssen beim Aufbau erneut geprüft werden.
IFS Europe und IFS 0,25° zählen nicht als unabhängige Modellfamilien.

Öffentliche Stichprobe für Berlin am 28.10.2026 um 10:04 UTC:
Alle drei Produkte lieferten GHI, DNI, DHI, Temperatur, Wind und Gesamtbewölkung
je Mitglied. Bei 72 angeforderten Stunden plus einem Rückblickpunkt waren es
20 Mitgliederspalten je Variable mit je 46 nichtleeren Zellen bei ICON-D2-EPS
und 51 Spalten mit je 73 nichtleeren Zellen bei beiden IFS-Produkten.
Das bestätigt nur die damalige Schnittstellenverfügbarkeit, keine physikalische
Qualifikation oder Vollständigkeit späterer Abrufe. Abgeleitete Strahlungsfelder
im Ensemble dürfen nicht mit nativen Feldern des deterministischen HRES
gleichgesetzt werden. Die öffentliche UI-Variablenliste und die tatsächliche
API-Antwort können voneinander abweichen; beide sind beim Adaptertest zu prüfen.

## 3. Abdeckung und Modellwechsel

Die künftige Auswahl erfolgt **je Zielintervall anhand gültiger Daten**, nicht
pauschal nach „Tag 1“, „Tag 2“ oder einem Modellnamen:

| Zeit ab Entscheidung | Geplanter Vergleich |
| --- | --- |
| 0–6 h | Regionalmodelle und globale Referenzen; lokale Einstrahlung/Nowcast als gesonderter Arm |
| 6–24 h | Schwerpunkt Regionalmodelle; IFS/GFS bleiben mit im Vergleich |
| 24–48 h | Weiterhin regionale Mitglieder, solange tatsächlich verfügbar; globale Fortsetzung muss jederzeit möglich sein |
| 48–72 h | HARMONIE gegebenenfalls noch teilweise verfügbar; ansonsten ICON-EU/IFS/GFS |
| 72 h bis zum angeforderten Ende | Gültige längere Modelle; geringere Priorität als die ersten 48 h |

Die Tabellenbereiche sind Auswertungsfenster, keine Behauptung garantierter
Modellverfügbarkeit. Kurze Arme werden auf der gemeinsamen Paarmenge verglichen;
der vollständige Kandidatenpfad mit Rückfall wird zusätzlich über das ganze
Entscheidungsfenster bewertet. So werden weder kurze Modelle wegen fehlender
Woche verworfen noch Rückfallfehler aus der Bewertung entfernt.

Der heutige [Enginepfad](../../custom_components/adaptive_solar/core/engine.py)
verwendet bereits die je Intervall verfügbaren Mitglieder und mittelt deren
PV-Leistungen gleichgewichtet. Er implementiert noch keine gelernte
horizontabhängige Gewichtung. Als Referenz bleibt diese Regel erhalten;
regionale Bevorzugung und aus älteren Daten gelernte Gewichte werden separat
gegen sie geprüft. Mitgliederausfälle, Gewichtsnormalisierung, Änderungen an
Modellgrenzen und passende Momentanreferenzen müssen reproduzierbar sein.

### 3.1 Begrenzung des bisherigen Wetterabrufs und Korrektur

Im veröffentlichten Stand 0.2.14 begrenzte `MODEL_DAYS` in
[weather.py](../../custom_components/adaptive_solar/weather.py) ICON-D2 und AROME France auf `forecast_days=2`.
Open-Meteo zählt diese Tage ab Tagesbeginn. Zwei Kalendertage sind daher keine
48 Stunden ab dem Abruf. Stundenbezogene Fenster sind über `forecast_hours`
und `past_hours` möglich.
[API-Zeitparameter](https://open-meteo.com/en/docs#api-documentation)

Eine öffentliche Stichprobe am 28.10.2026 um 09:56 UTC für Berlin
(52,52° N, 13,41° E; kein privater Anlagenstandort) ergab:

| ICON-D2-Abfrage | Letzter Zeitstempel mit allen sechs heutigen Wettergrößen |
| --- | --- |
| `forecast_days=2` | 29.10.2026, 23:00 UTC |
| `forecast_hours=72` | 30.10.2026, 06:00 UTC; spätere Zellen fehlend |

Damit endete die Kalendertage-Abfrage sieben Stunden früher als die gültigen
Daten der zweiten Antwort. Dies ist eine datierte Schnittstellenbeobachtung,
kein dauerhaft garantierter Horizont oder Genauigkeitsnachweis. Strahlung bei
Zeitstempel `t` beschreibt die vorangegangene Stunde.

Der Entwicklungsstand fordert `forecast_hours=(forecast_days+1)*24+1` und
`past_hours=1` an. Das berücksichtigt Randstützstellen und Zeitzonenreserve;
der Parser erhält fehlende Werte und die Ausgabe bleibt auf die konfigurierten
lokalen Kalendertage beschränkt. Beide Zeitumstellungen sind getestet.
Morgen/übermorgen als lokale Kalendertage und rollierende 24/48 Stunden bleiben
verschiedene Aufgaben. Der separate Host-Collector fordert standardmäßig 193
Stunden an, ohne kurze Modelle auf zwei Kalendertage abzuschneiden.

Bei denselben öffentlichen Stichproben lieferten IFS HRES, GFS, ICON-EU,
AROME France und KNMI Europe die angefragten Variablen mit unterschiedlichen
Endzeiten. KNMI Netherlands war in Berlin nicht verfügbar, am Beispiel Aachen
hingegen schon. Modellkennung, Gebietsabdeckung und zurückgegebene Gitterposition
sind deshalb vor Aufnahme am tatsächlichen Standort zu prüfen.

## 4. Archivumfang und Abrufe

Der [Archivierungsentwurf](physikvergleich-und-archivierung.md) gilt für alle
Arme. Zusätzlich werden folgende Angaben verbindlicher Teil des Datenvertrags:

- Angeforderte Modellkennung, Endpoint und bereinigte Anfrageparameter;
  Standort/Gitterpunkt und Höhenbehandlung in privaten Metadaten.
- Unveränderte Antwort, Empfangszeit, bekannte Laufmetadaten, Zeitauflösung,
  Einheiten und tatsächliche gültige Intervalle je Pflichtvariable.
- Originale GHI/DNI/DHI, Temperatur, Wind und Gesamtbewölkung; als zusätzliche
  Forschungseingaben Wolkenschichten, relative Feuchte, Niederschlag/Schnee und
  gegebenenfalls Nebel/Sichtweite, soweit das jeweilige Modell sie liefert.
- Bei ICON-D2 zusätzlich verfügbare 15-Minuten-Strahlung für den Versuch mit
  feinerer Zeitintegration. Interpolierte Viertelstunden sind als solche zu
  kennzeichnen; sie schaffen keine zusätzliche Wolkeninformation.
- Eindeutige Verknüpfung von Quellen, Einzelmodell-PV-Ergebnissen, Mitgliedern,
  Gewichten, Konfiguration, Ausgabe und späteren qualifizierten Istwerten.
- Bei Ensembles zusätzlich erwartete und empfangene Mitglieder, Kontrolllauf
  soweit vorhanden, Lauf-/Mitgliedskennung, fehlende Zellen und vollständige
  gemeinsame Zeitverläufe aller Wettervariablen. Ausgabequantile allein reichen
  für spätere Physik-, Kalibrierungs- oder Speichervergleiche nicht aus.

Fehlende optionale Forschungsvariablen dürfen die brauchbaren Kerndaten nicht
verwerfen. Fehlende Pflichtgrößen qualifizieren dagegen keine vollständige
Physikzelle. Produktionsinputs kommen weiterhin aus HA; zusätzliche
Forschungsmodelle kann der Archivhost separat abrufen. Beide Herkunftswege und
ihre tatsächliche Verfügbarkeit bleiben getrennt.

Der fünfminütige HA-Exportabruf ist unabhängig vom Wetterabruf. Für zusätzliche
Forschungsmodelle ist zunächst ein stündlicher Collector mit Deduplizierung und
gezielten Abrufen vor festgelegten Entscheidungszeiten sinnvoll; Rate und
Verfügbarkeitsnachweis sind im Pilot zu messen. Identischer Inhalt kann einmal
gespeichert werden, Abrufereignisse bleiben erhalten. Provider-Updateanzeigen
beweisen keine atomare Verfügbarkeit auf allen Servern.
[Open-Meteo-Bereitstellung](https://open-meteo.com/en/docs/model-updates)

Für nichtkommerzielle Nutzung nennt Open-Meteo derzeit Grenzen von 600 Calls/min,
5.000/h, 10.000/Tag und 300.000/Monat. Größere Variablenpakete können mehrfach
zählen; HA und Forschungscollector benötigen ein gemeinsames Abrufbudget.
API-Daten stehen unter CC BY 4.0; Herkunft und Lizenzhinweise bleiben im Archiv.
[Nutzungsbedingungen](https://open-meteo.com/en/terms),
[Call-Berechnung](https://open-meteo.com/en/pricing),
[Datenlizenz](https://open-meteo.com/en/licence).

Ensemblekosten und Datenvolumen werden getrennt gemessen: Mitgliedszahl,
Parameter, Zeitfenster und Abrufhäufigkeit gehen in die Planung ein. Die
öffentlichen Ensemble-Stichproben waren ohne Schlüssel abrufbar; daraus folgt
keine Verfügbarkeitsgarantie. Die kommerzielle Tarifseite nennt für Ensemblezugang
Professional oder höher; dies ist von den Bedingungen der nichtkommerziellen
öffentlichen Nutzung zu unterscheiden. Vor Inbetriebnahme den gewählten Zugang
und sein Budget erneut prüfen. [Tarifumfang](https://open-meteo.com/en/pricing)

## 5. Bewertung für Akkuentscheidungen

Die primäre Bewertung erfolgt getrennt für 0–24 und 24–48 Stunden sowie für
konkrete Morgen-/Abendentscheidungen. Stundenenergie, verbleibende Tagesenergie,
Energie bis zum nächsten Ladefenster, Bias und besonders große Über- und
Unterschätzungen werden separat ausgewiesen. Wetterlagen wie Hochnebel,
wechselnde Bewölkung und klare Tage sowie Jahreszeiten sind eigene Strata.
Auf ausreichend vielen späteren Prüftagen eingefrorene Kandidaten vergleichen;
keine Auswahl anhand immer wieder derselben Testtage.

Für „Akku möglichst voll halten oder Platz schaffen“ ist die Fehlerverteilung
entscheidend. Überschätzte PV kann zu unnötigem Entladen und späterem Netzbezug
führen; unterschätzte PV kann Speicherplatz und nutzbaren Ertrag kosten.
Welche Seite schwerer wiegt, hängt unter anderem von Last, Reservebedarf,
Einspeisung und Preisen ab. Diese Annahmen müssen vor einer Entscheidungssimulation
feststehen. PV-Ertrag allein legt keine sinnvolle Akkuaktion fest.

### 5.1 Von Ensemblemitgliedern zu Ertragswahrscheinlichkeiten

Jedes vollständige Wettermitglied durchläuft separat die PV-Physik mit derselben
Geometrie, Verschattung und Ausgangsbegrenzung. Erst dessen Leistungen werden
über das betreffende Zeitfenster integriert. Bei mehreren Anlagen bleiben
dieselben Wettermitglieder über alle Stufen gekoppelt; erst die gemeinsame
Energie je Szenario wird zur Gesamtverteilung zusammengefasst. Aus den so entstehenden
Energieszenarien lassen sich beispielsweise folgende Ausgaben bilden:

- Unteres, mittleres und oberes Ertragsquantil: hier ausdrücklich statistische
  Nichtüberschreitungsquantile Q10/Q50/Q90; kein Wechsel zur in Teilen der
  Energiewirtschaft verwendeten Überschreitungsnotation.
- Wahrscheinlichkeit, dass morgen mindestens eine vorab definierte Energiemenge
  erzeugt wird, oder dass bis zum nächsten Ladefenster ein Defizit entsteht.
- Anteil der Szenarien mit Speicherüberlauf beziehungsweise Reserveunterschreitung
  unter einer festgelegten Last- und Speicherpolitik.

Eine rohe Quote von etwa 16 aus 20 Mitgliedern über einer Energieschwelle ergibt
80 % Ensembleanteil, aber noch keine lokal bestätigte Eintrittswahrscheinlichkeit.
Endliche Mitgliedszahl, gemeinsame Modellfehler und die PV-Umrechnung begrenzen
die Aussage. Rohverteilung und kalibrierte Ausgabe werden getrennt archiviert,
einschließlich Kalibrierungsstand und Trainingsstichtag.
Erwartete und gültige Mitgliedszahl bleiben sichtbar. Mindestabdeckung und
Umgang mit fehlenden Mitgliedern werden vorab festgelegt; fehlende Werte sind
keine Nullszenarien. Bei unzureichender Abdeckung folgt ein gekennzeichneter
Rückfall auf eine vollständige Quelle oder keine Wahrscheinlichkeitsausgabe.

**Zeitliche Zusammenhänge müssen erhalten bleiben.** Tagesenergiequantile
entstehen nicht durch Addition stündlicher Q10-Werte. D2-Mitglied 1 darf nicht
am Horizontende mit IFS-Mitglied 1 zu einem vermeintlich kohärenten 48-h-Szenario
verbunden werden. Für ein nicht mehr vollständig durch D2 abgedecktes Fenster
liefert zunächst IFS die vollständigen Szenarien; D2 bleibt für kürzere
vollständige Fenster nutzbar. Eine spätere Kombination ganzer Verteilungen
braucht eine eigene geprüfte Methode. Familiengewichte werden getrennt von
Mitgliedergewichten festgelegt, damit 51 IFS-Mitglieder nicht automatisch
51/71 Gewicht gegenüber 20 D2-Mitgliedern erhalten. Verwandte Produkte dürfen
keine künstliche Sicherheit durch Doppelzählung erzeugen.

### 5.2 Wahrscheinlichkeiten prüfen und kalibrieren

Ergänzend zum Punktprognosefehler werden CRPS für die gesamte Ertragsverteilung,
Quantilverlust, Abdeckung und Breite des Q10–Q90-Bands sowie Brier Score und
Zuverlässigkeitskurven für definierte Energieschwellen geprüft. Ein nominales
80-%-Band soll langfristig entsprechend häufig treffen und dabei informativ
eng bleiben. Ergebnisse werden nach Vorlauf und Wetterlage ausgewiesen;
Kalibrierung benutzt ausschließlich ältere verfügbare Paare, die Bewertung
unangetastete spätere Tage. Bei geringer Datenbasis bleibt der Status
„unkalibriertes Ensemble“ sichtbar, ohne Scheingenauigkeit.
[Methoden zur probabilistischen Solarprognose](https://doi.org/10.1016/J.SOLENER.2022.12.054),
[Solar Forecast Arbiter: Metriken](https://forecastarbiter.epri.com/metrics/).

Wetterstreuung allein erfasst nicht alle Fehler der Anlage, etwa Schatten-,
Temperatur- oder Messfehler. Daher ist die Kalibrierung an der tatsächlichen
PV-Ausgangsgrenze erforderlich. Eine aktuelle Untersuchung an sieben
ungarischen PV-Anlagen bestätigt den Nutzen statistischer Nachbearbeitung,
ohne einen entsprechenden Gewinn für diese Anlage zu beweisen.
[Studie zur Nachbearbeitung von PV-Ensembles](https://www.sciencedirect.com/science/article/pii/S0038092X26000496)

Für einen späteren Steuerungsvergleich zusätzlich Lastprognosen und damalige
Istwerte, SoC,
nutzbare Kapazität, Wirkungsgrade, Leistungsgrenzen, Restriktionen und gegebenenfalls
Tarife mit ihrer Verfügbarkeit erfassen. Diese Daten bleiben in einer optionalen
privaten Erweiterung; der PV-Kern bleibt hardwareunabhängig.

## 6. Umsetzung und Abnahme

1. Deterministische Modelle, ICON-D2-EPS, IFS-ENS und geeignete regionale
   Zusatzarme am tatsächlichen Standort
   auf Variablen, Gitterlage und zeitliche Abdeckung prüfen; das bestätigt noch
   keine Genauigkeit.
2. Den Archivvertrag auf mehrere Modelle, vollständige Ensemblemitglieder und
   unterschiedliche Endzeiten auslegen. 24 Monate Aufbewahrung;
   Speicherbewertung zunächst nach drei,
   erneut nach sechs Monaten ab Aufnahmestart als Planungsrhythmus.
3. Den Abruf mit ausreichend langen Zeitfenstern vorbereiten. Bestehende
   Parsersemantik, nächtliche Lücken, Randpunkte und beide DST-Wechsel bewahren.
4. Referenz aus den eingefrorenen Eingaben offline reproduzieren. Regional- und
   Globalarme zunächst mit identischer PV-Physik vergleichen; Physikänderungen
   danach getrennt untersuchen.
5. Horizontabhängige Kandidaten einschließlich ihrer Rückfallpolitik prüfen.
   Ergebnisse für die ersten zwei Tage haben Vorrang, spätere Horizonte und
   Ausfälle bleiben sichtbar. Ensemble-Replay und Wahrscheinlichkeitsprüfung
   sind eigene Abnahmepunkte: vollständige Mitglieder, konsistente Energiequantile,
   keine willkürlichen Verknüpfungen über Modellgrenzen, chronologische Kalibrierung
   und unabhängige Prüfung von Verteilungs- und Schwellenprognosen.
   Anschließend gegebenenfalls eine eigenständige
   Entscheidungssimulation mit vorab fixierten Randbedingungen durchführen.

Der Entwicklungsstand implementiert die Aufnahme zusätzlicher Modelle und echter
Ensembles, Originalarchiv und Offline-Replay. [Archivbetrieb](../archiv/archivbetrieb.md)
beschreibt Vollständigkeitsregeln, Familiengewichtung, Quantile und die begrenzte
Median-Biaskorrektur. Lokale Streuungskalibrierung, gelernte produktive Gewichte
und Akkuaktionen stehen aus. Die produktive Integration behält die bestehende
Gleichgewichtung der verfügbaren deterministischen Modelle. Details zu
chronologischen Vergleichen und Mindestumfang stehen im
[Validierungsplan](../entwicklung/validierung.md) und in
[AS-OPT-07](adaptive-solar-bewertung.md#as-opt-07-gewichte-und-auswahl-der-wettermodelle).
