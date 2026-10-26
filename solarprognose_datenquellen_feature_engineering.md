# Solarprognosen: Datenquellen und Feature-Engineering

Stand: 26.10.2026. Grundlagenrecherche mit direkt zugeordneten Primärquellen.
Beispielverfahren sind keine zusätzliche Adaptive-Solar-Implementierung. Die
[Integration](README.md) verwendet aktuell die Open-Meteo-Forecast-API und optionale
HA-Sensoren; weitere Datenquellen sind Forschungskandidaten.

## 1. Wetter-APIs und Ausgabestände

### 1.1 Open-Meteo

Die [Forecast-API](https://open-meteo.com/en/docs) bietet Wettervorhersagen verschiedener
Modelle. Adaptive Solar fordert stündliche GHI/DNI/DHI, Temperatur, Wind und Bewölkung
mit expliziten Einheiten/UTC-Zeiten an. Unterschiedliche räumliche Raster und angebotene
15-Minuten-Produkte machen die implementierte Stundenprognose nicht zu einer
hochaufgelösten gemessenen Kurve.

Die freie gehostete API ist für nichtkommerzielle Nutzung unter den
[Nutzungsbedingungen](https://open-meteo.com/en/terms) vorgesehen. Am 26.10.2026 nennen
diese Grenzen unter 10.000 Aufrufen pro Tag, 5.000 pro Stunde und 600 pro Minute;
Attribution und tatsächliche Abfragegewichtung beachten. Datenlizenz, Lizenz des
Servers und API-Nutzungsrecht sind verschiedene Fragen. Details zum lokalen Request
und zu Standortdaten stehen unter [Datenschutz](docs/datenschutz.md).

### 1.2 Historische Forecasts, einzelne Läufe und Previous Runs

Die [Historical Forecast API](https://open-meteo.com/en/docs/historical-forecast-api)
verbindet kurze Anfänge archivierter Läufe zu einer Zeitreihe. Der Anbieter nennt
modellabhängige Abdeckung ungefähr ab 2022. Sie ist kein vollständiger damaliger
Day-ahead-Verlauf. Die frühere pauschale Angabe „ab 2021“ galt nicht allgemein.

[Previous Runs](https://open-meteo.com/en/docs/previous-runs-api) ordnet Werte festen
Leadversätzen zu; die meisten Modelle sind dort ab 2024 archiviert, einzelne
Variablen haben längere Historie. Für vollständige Laufhorizonte stellt Open-Meteo
ein gesondertes Single-Runs-Angebot bereit. In allen Fällen müssen Run, Zielzeit,
angenommene bzw. belegte Verfügbarkeit und tatsächlicher Abruf erhalten bleiben.
Ein nachträglich abgerufener Lauf allein beweist keinen damaligen lokalen Empfang.

### 1.3 Direkte Wetterdienste und alternative APIs

[DWD Open Data](https://opendata.dwd.de/) stellt Wetterprodukte bereit;
[ECMWF Open Data](https://www.ecmwf.int/en/forecasts/datasets/open-data) beschreibt
seine aktuellen offenen Produkte und CC-BY-4.0-Bedingungen. Räumliches Raster,
Ausgabezeit, Latenz und Variablen jeweils im gewählten Produkt prüfen. Rohes GRIB
oder ein Provider-Endpunkt ist nicht automatisch derselbe Wetterstand wie eine
bereits empfangene Open-Meteo-Ausgabe.

Andere Wetter-APIs werden hier ohne neu geprüften Tarif und Variablenumfang nicht
als kostenlose Solarstrahlungsquelle empfohlen. Insbesondere UV-Index und
Beleuchtungsstärke ersetzen keine GHI/DNI/DHI-Messung.

## 2. Strahlungsdaten: Beobachtung, Reanalysis und PVGIS

| Quelle / Primärdokumentation | Datenart | Geeignete Rolle und Grenze |
| --- | --- | --- |
| [ERA5](https://cds.climate.copernicus.eu/datasets/reanalysis-era5-single-levels) | Nachträgliche Reanalysis, stündlich ab 1940 | Wetter-/Saisondiagnose; kein ursprünglich verfügbarer Day-ahead-Forecast |
| [CAMS Solar Radiation](https://atmosphere.copernicus.eu/solar-radiation-services) | Strahlungsprodukte mit satelliten-/atmosphärischen Eingaben | Strahlungsdiagnose; Produkt, Auflösung, Region, Zugang und Lizenz prüfen |
| [PVGIS API](https://joint-research-centre.ec.europa.eu/photovoltaic-geographical-information-system-pvgis/using-pvgis-5/api-non-interactive-service_en) | Historische Ertrags-/Strahlungszeitreihen, typische Jahre und Horizont | Plausibilität und Szenarien; kein realer Anlagenzähler und keine operative Wettervintage |
| Eigene Pyranometer-/PV-Messung | Standortbeobachtung | Referenz nur bei geklärter Einheit, Ausrichtung, Kalibrierung und Zeitunterstützung |

Eine Reanalysis kann mit späteren Beobachtungen erstellt worden sein. Ein damit
trainierter retrospektiver Versuch beantwortet eine andere Frage als ein Modell,
das nur ursprüngliche Wetterprognosen verwendet. Vergleichsarme entsprechend benennen.

## 3. Satellitenbasierte Strahlung

Satelliten schätzen Wolken-/Strahlungsverhältnisse über Flächen, ein lokaler Sensor
misst am Standort. Eine Satellitenzelle ist keine zertifizierte Referenz für eine
verschattete Solarfläche. Für Nowcasting sind zusätzlich Bildzeit, Empfangsverzug,
Wolkenbewegung und Aktualisierungsrhythmus relevant.

Das [Open-Meteo-Satellitenangebot](https://open-meteo.com/en/docs/satellite-radiation-api)
ist ein gesonderter Endpunkt und wird von Adaptive Solar derzeit nicht abgerufen.
Pauschale RMSE-Bereiche ohne Produkt, Region, Referenz und Zielhorizont wurden entfernt.

## 4. Historische PV-Daten

Die wichtigste Lernreferenz des Projekts ist kumulative PV-Energie am erklärten
AC-Wechselrichter- oder DC-Reglerausgang. Ein Zähler muss frische Originalberichte,
Resetverhalten, Lücken und betriebliche Abregelung nachvollziehbar machen. Ein
Summenzähler identifiziert keine Einzelstring-Verluste. Ein DC-Ausgang ist weder
AC-Erzeugung noch automatisch Batterieladung.

Externe Datensätze und Communityplattformen können für Methodenversuche nützen.
Ohne Sensor-/Geometrie-/Zeitzonen-/Lizenzmetadaten qualifizieren sie aber weder die
eigene Anlage noch deren Lernlabels. Vor Veröffentlichung fremder Anlagenzeitreihen
Einwilligung und Datenlizenz prüfen; keine privaten Testdaten in Git übernehmen.

Für dieses Repository liest [capture_actuals.py](scripts/capture_actuals.py) Recorder-
`change`-Energie statt kumulativer `sum`. Die Zahlen brauchen zusätzliche echte
Qualitätsevidenz. [Aufnahmeleitfaden](docs/benchmark-aufnahme.md).

## 5. Feature Engineering

### 5.1 Clear-Sky-Index und Solarposition

Für eine Klarhimmelreferenz liefert [pvlib](https://pvlib-python.readthedocs.io/en/stable/reference/clearsky.html)
mehrere Modelle; [Sonnenposition](https://pvlib-python.readthedocs.io/en/stable/reference/solarposition.html)
ist deterministisch aus Zeit und Standort berechenbar. Ein gemessener Clear-Sky-Index
und der extraterrestrische Clearness-Index haben verschiedene Nenner und sollten
nicht ununterschieden als `Kt` bezeichnet werden. Kleine Nenner am Horizont sperren.

Die aktuelle Integration nutzt Haurwitz im GHI-Normalisierungspfad und eine
Ineichen-Form für Momentanreferenzen; identische Zeitunterstützung ist dabei wichtig.
Das ist eine Modellapproximation, keine Messung sub-stündlicher Wolken.

### 5.2 Temperatur, Wind und Anlagenmerkmale

PVWatts verwendet einen modulspezifischen Temperaturkoeffizienten; seine Einheit ist
1/°C, nicht Prozent ([pvlib-PVWatts](https://pvlib-python.readthedocs.io/en/stable/reference/generated/pvlib.pvsystem.pvwatts_dc.html)).
Der Projektdefault −0,004/°C entspricht −0,4 %/°C; er ist kein universeller Modulwert.
Temperatur und Wind beeinflussen die angenäherte Zelltemperatur, Stringausrichtung
und nominelle Leistung die Baseline. Eine Verlustkonfiguration ist keine Messung.

### 5.3 Zeitmerkmale, Lags und Rolling Statistics

Sinus-/Kosinusmerkmale kodieren zyklische Zeit oder Sonnenazimut. Lags und rollende
Statistiken dürfen nur Daten verwenden, die bereits vor Forecastausgabe vorlagen.
Eine rückwärts gerichtete Zeitstempelbeschriftung allein beweist diese Verfügbarkeit
nicht; verspätete Messungen und Revisionen brauchen eigene Empfangszeiten.

Der aktuelle Lerner verwendet keine zusätzlichen Residual-Lagfeatures. Solche
Merkmale wären separat zu archivieren und auf späteren Zieltagen zu prüfen, statt
unbemerkt in die bestehende Historie hineinzurechnen.

## 6. Datenqualität und Missing Data Handling

Fehlende Messwerte bleiben für Training und Benchmark fehlend. Nacht wird nicht
allein aufgrund eines Zählerlochs zu gemessenen 0 kWh erklärt. Ein Reset darf keine
Brücke über die Störung erzeugen. Interpolation/Forward-Fill und Clear-Sky-Ersatz
können in ausdrücklich synthetischen Experimenten vorkommen, sind aber keine
qualifizierten Originalenergielabels.

Adaptive Solar verlangt mindestens halbstündige Zielzellen, mindestens 95 %
Messabdeckung und höchstens 2,5 % Lücke an jedem Rand. Diese konkreten Projektgates
stehen im [Vertrag](docs/implementation-contract.md). Starre globale Prozentwerte
für „typische“ Ausfälle, Ausreißer oder Quellenqualität sind nicht belegt und werden
nicht als Zertifizierung verwendet.

## 7. Datenpipelines und Automatisierung

Für Fremdexperimente sind Skripte, Datenbanken und Scheduler mögliche Bausteine.
Die deploybare Integration nutzt dagegen native HA-Koordination und lokale Stores;
kein Cronjob, SQLite-Schema oder Prefectserver muss dafür eingerichtet werden.
Die früheren frei erfundenen `fetch_data.py`-/`retrain.py`-Cronpfade wurden entfernt.

Reproduzierbare Werkzeuge im Projekt sind [forecast.py](scripts/forecast.py),
[capture_ha.py](scripts/capture_ha.py), [capture_actuals.py](scripts/capture_actuals.py)
und [evaluate.py](scripts/evaluate.py). Liveabruf, Aufnahme und Auswertung sind
unterschiedliche Modi mit unterschiedlichen Evidenzgrenzen. Geplante tatsächliche
Aufnahmen benötigen vorher festgelegte Cutoffs und vollständige Zielpläne.

## 8. Quellen und nächste Prüfung

Die Primärquellen sind an den betreffenden Datenarten verlinkt und wurden für diese
Konsolidierung am 26.10.2026 herangezogen. Angebote ändern sich; für die Einführung
einer weiteren Quelle deren aktuellen Produktumfang, Lizenz, Tarif, Zeitsemantik
und regionale Eignung erneut prüfen. Kein hier genanntes Produkt belegt für sich
bessere Forecastgüte. Der [Validierungsplan](docs/validierung.md) verlangt einen
separaten fairen prospektiven Vergleich gegen beide Referenzen.
