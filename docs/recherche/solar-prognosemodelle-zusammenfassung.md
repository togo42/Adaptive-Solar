# Solar-Prognosemodelle und Tools für private Anwendungen

Stand: 26.10.2026. Vergleich von Funktionen, Zugang und Prüfbedarf.
Kostenloser Dienstzugang, freie Daten und Open-Source-Code sind verschiedene Dinge.
Es gibt hier keine standortübergreifende Genauigkeitsrangliste. Die
[Adaptive-Solar-Integration](../../README.md) wird [separat validiert](../entwicklung/validierung.md).

## Inhaltsverzeichnis

1. [Open-Meteo](#1-open-meteo)
2. [Forecast.Solar](#2-forecastsolar)
3. [pvlib-python](#3-pvlib-python)
4. [Solcast](#4-solcast)
5. [Andere Wetter-APIs](#5-andere-wetter-apis)
6. [Open-Source-Projekte](#6-open-source-projekte)
7. [Home Assistant Integrationen](#7-home-assistant-integrationen)
8. [Vergleichstabelle](#8-vergleichstabelle)
9. [Auswahl und Bewertung](#9-auswahl-und-bewertung)

## 1. Open-Meteo

Die [Forecast-API](https://open-meteo.com/en/docs) liefert Wetter einschließlich
Solarstrahlungsvariablen. Zur PV-Erzeugungsprognose kommt eine Anlagenumrechnung
hinzu. Adaptive Solar fragt GHI/DNI/DHI, Temperatur, Wind und Bewölkung ab.
Region, Modell und Variable bestimmen Horizont und Auflösung.

Die [Nutzungsbedingungen](https://open-meteo.com/en/terms) erlauben die freie
gehostete API für nichtkommerzielle Zwecke, darunter private Hausautomation;
Attribution und Limits gelten. Die Daten stehen unter CC BY 4.0, der
[Servercode](https://github.com/open-meteo/open-meteo) hat eine eigene Lizenz.
Aus der Datenlizenz folgt kein uneingeschränkter kostenloser APIzugang.

[Historical Forecast](https://open-meteo.com/en/docs/historical-forecast-api)
verbindet kurze Anfänge archivierter Läufe; die Abdeckung beginnt modellabhängig
ungefähr 2022. [Previous Runs](https://open-meteo.com/en/docs/previous-runs-api)
und einzelne Laufhorizonte sind davon zu unterscheiden. Nachträgliche Archive
beweisen keinen ursprünglichen lokalen Empfang. Weitere Details:
[Datenquellen](solarprognose_datenquellen_feature_engineering.md).

## 2. Forecast.Solar

[Forecast.Solar](https://doc.forecast.solar/) ist ein externer PV-Prognosedienst;
die [native HA-Integration](https://www.home-assistant.io/integrations/forecast_solar/)
verbindet ihn mit Home Assistant. Standort, Ausrichtung und Anlagenleistung gehören
zur Konfiguration. Tarifabhängige Funktionen und Abrufgrenzen beim Anbieter prüfen,
keine maximale Produktfunktion pauschal dem kostenlosen Zugang zuschreiben.

Ein Vergleich benötigt denselben Messpunkt und denselben rechtzeitig archivierten
Forecastcutoff. Einzelne Communityberichte erlauben keine allgemeine Einstufung
als genauer oder ungenauer gegenüber anderen Diensten.

## 3. pvlib-python

[pvlib](https://pvlib-python.readthedocs.io/) ist eine Bibliothek für PV-Modellierung,
keine eigenständige Wetterprognose. Sie bietet unter anderem Sonnenstand,
Clear-Sky-Modelle, Transposition, Zelltemperatur und PV-Leistungsmodelle.
Die [ModelChain-Referenz](https://pvlib-python.readthedocs.io/en/stable/reference/modelchain.html)
beschreibt die konfigurierbaren Bausteine. Die Bibliothek steht unter
[BSD-3-Clause](https://github.com/pvlib/pvlib-python/blob/main/LICENSE).

Ein universeller MAE- oder nRMSE-Bereich ist aus der Bibliothek nicht ableitbar.
Die frühere pauschale Fehlerzahl wurde mangels bestimmter Primärmessung entfernt.
MAE ist nicht RMSE; eine Normalisierung benötigt einen ausdrücklich definierten
Nenner. Wetterqualität, Parametrisierung, Standort, Horizont und Nachtfilter
bestimmen den Fehler des konkreten Gesamtsystems.

## 4. Solcast

Das [private Rooftop-Angebot](https://www.solcast.com/free-rooftop-solar-forecasting)
ist für den eigenen Wohnstandort und nichtkommerzielle Nutzung vorgesehen.
Der Anbieter nennt bis zu zehn API-Anfragen täglich und einen Standort mit bis zu
zwei Neigungs-/Azimutkombinationen; eine Wohnstandortprüfung ist vorgesehen.
Weitergabe von Daten und Attribution unterliegen zusätzlichen Bedingungen.

Dies ist ein möglicher externer Vergleichskandidat, kein belegter allgemeiner
Genauigkeitssieger. Andere Solcast-Produkte oder kostenpflichtige Leistungsmerkmale
sind nicht automatisch Bestandteil dieses Angebots. Bedingungen vor Nutzung prüfen.

## 5. Andere Wetter-APIs

[OpenWeather](https://openweathermap.org/api) und andere APIs haben verschiedene
Produkte, Tarife, Variablen und Zugangsbedingungen. Ein kostenloser Wettertarif ist
kein Nachweis kostenloser GHI/DNI/DHI-Daten. Hier wird ohne konkrete frisch geprüfte
Produktzuordnung weder ein kostenloses Solarpaket zugesagt noch eine pauschale
Kostenpflicht aller Strahlungsprodukte behauptet. Adaptive Solar nutzt diese APIs nicht.

## 6. Open-Source-Projekte

| Projekt / Primärquelle | Einordnung |
| --- | --- |
| [Open Climate Fix Quartz](https://github.com/openclimatefix/open-source-quartz-solar-forecast) | Eigenständiger PV-Forecastansatz; Datenherkunft, Modellversion und regionale Übertragbarkeit vor Übernahme prüfen |
| [rany2/open-meteo-solar-forecast](https://github.com/rany2/open-meteo-solar-forecast) | Pythonprojekt für PV-Prognose aus Open-Meteo-Wetter; dessen eigene Physik-/API-Semantik beachten |
| [Solar Forecast Arbiter](https://github.com/SolarArbiter/solarforecastarbiter-core) | Werkzeuge und Datenmodell für nachvollziehbare Prognosebewertung |
| [Adaptive Solar](../../README.md) | Dieses Repository: explizite AC/DC-Ausgangsstufen, Physik und lokale prospektive Residuen |

Modellgewichte, Drittanbieterbibliotheken und Daten behalten eigene Lizenzen. Ein
öffentliches GitHub-Projekt ist nicht automatisch uneingeschränkt wiederverwendbar.
Erfolgszahlen fremder Projekte werden hier ohne vollständige reproduzierbare
Versuchszuordnung nicht zu einer Rangliste oder eigenen Gütezusage verdichtet.

## 7. Home Assistant Integrationen

[Forecast.Solar](https://www.home-assistant.io/integrations/forecast_solar/) ist eine
native HA-Integration; [Open-Meteo Solar](https://github.com/rany2/ha-open-meteo-solar-forecast)
und [Helios Forecast](https://github.com/ReikanYsora/Helios-Forecast) sind eigenständige
Referenzprojekte. Ihre aktuelle Version und jeweilige Konfiguration vor einem
Vergleich festhalten. Ein anderer Dämpfungs-/Horizontparameter muss nicht dieselbe
physikalische Semantik haben.

Adaptive Solar wird über ein benutzerdefiniertes HACS-Repository oder manuell
installiert. [Installationsweg und Plattformgrenzen](../anwendung/installation.md).
Es importiert keinen Helios-Modellcode und übernimmt nicht automatisch dessen
Lernhistorie. Die interne ML-Prüfung gegen die eigene Physik ersetzt den externen
Vergleich gegen diese Referenzintegrationen nicht.

## 8. Vergleichstabelle

| Komponente | Liefert | Benötigt | Eignung vor Ort prüfen |
| --- | --- | --- | --- |
| Open-Meteo API | Wetter-/Strahlungsprognosen | Standort, Produkt-/Modellauswahl und API-Bedingungen | Wetter-/Vintageabdeckung |
| pvlib | Physikalische Berechnungen | Passendes Wetter und Anlagenparameter | Modellannahmen und Messgrenze |
| Forecast.Solar | Externe PV-Prognose | Anbieterzugang und Konfiguration | Tarifumfang und gepaarter lokaler Fehler |
| Solcast Rooftop | Externe PV-Prognose | Qualifizierter privater Zugang | Bedingungen, Abrufbudget und gepaarter lokaler Fehler |
| Open-Meteo Solar / Helios | Jeweilige Integrationsprognose | Deren Setup und Historie | Identische Module, Grenzen, Cutoffs und Messreferenz |
| Adaptive Solar | Physik-/Residualprognose | HA und Binärbasis; lokale Energie für Lernen | Qualifizierte Historie und bisher offener Feldnachweis |

## 9. Auswahl und Bewertung

Für einen Einstieg zuerst verfügbares Wetter, Messgrenze, Installationsfähigkeit und
Datenrechte klären. Dann eine einfache nachvollziehbare Baseline festlegen.
Ein größerer Modellstack oder ein Anbietername ersetzt keine Messung.
[ML-Methoden](solar_ml_research.md) und [Ensembles](ensemble_hybrid_solar_forecasting.md)
beschreiben Optionen, keine garantierten Verbesserungsprozente.

Für dieses Projekt verlangt der [Validierungsplan](../entwicklung/validierung.md) mindestens
30 vollständige gepaarte Zieltage je deklariertem Stufen-/Horizontstratum sowie
Fehler-, Bias- und Abdeckungsprüfung gegen beide Referenzen. Eine Saison ist kein
Ganzjahresnachweis. Tageslicht und Nacht, Ausfälle und Abregelung sichtbar halten;
fehlende Prognosen nicht zu Null machen und frühe Physikfallback-Tage nicht entfernen.
