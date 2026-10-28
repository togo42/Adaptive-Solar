# Recherche: Physikalische und NWP-basierte Solarprognosemodelle

Stand: 26.10.2026. Methodenüberblick mit direkt zugeordneten Primärquellen.
Er ersetzt die frühere Gegenüberstellung nicht einheitlich dokumentierter
Fehlerzahlen. Ohne Originaldatensatz, Region, Zeitbasis und Forecastvintage werden
keine typischen MAE-/RMSE-Werte oder festen Modellübergangshorizonte behauptet.
Die konkrete [Adaptive-Solar-Pipeline](docs/implementation-contract.md) ist von den
hier beschriebenen Alternativen zu unterscheiden.

## 1. Clear-Sky-Modelle (Klarheitsstrahlungsmodelle)

Clear-Sky-Modelle berechnen eine Strahlungsreferenz für wolkenfreien Himmel.
Sie sind keine Bewölkungsprognose. Ein Fehler dieser Referenz kann die Normalisierung
beeinflussen; daraus folgt keine allgemeine Fehleruntergrenze oder zwingende
1:1-Übertragung durch spätere Korrekturen.

### 1.1 Ineichen–Perez

[pvlib Ineichen](https://pvlib-python.readthedocs.io/en/stable/reference/generated/pvlib.clearsky.ineichen.html)
verwendet unter anderem Sonnengeometrie, absolute Luftmasse, Linke-Turbidität und
Standorthöhe für GHI/DNI/DHI. Eine Klimatologie für Trübung ist keine aktuelle lokale
Aerosolmessung. Adaptive Solar verwendet eine Ineichen-Form für Momentanreferenzen,
nicht als Ersatz für fehlende prospektive Wetterdaten.

### 1.2 Haurwitz

Die [pvlib-Implementierung](https://pvlib-python.readthedocs.io/en/stable/reference/generated/pvlib.clearsky.haurwitz.html)
liefert GHI in **W/m²**. Für positive Sonnenhöhe lautet die Näherung
$GHI = 1098\sin(h_s)\exp(-0.059/\sin(h_s))$.
Sie benötigt keine aktuelle atmosphärische Trübungsmessung, bildet damit aber
auch nicht deren örtliche Variation ab. Die frühere Einheit kJ/(m²·h) und der
abweichende Exponent wurden mit der tatsächlich verwendeten Bibliothek abgeglichen.
Im Projekt dient Haurwitz der GHI-Normalisierung bei geeignetem Sonnenstand.

### 1.3 Weitere Clear-Sky-Ansätze

Die [pvlib-Clear-Sky-Referenz](https://pvlib-python.readthedocs.io/en/stable/reference/clearsky.html)
führt weitere Ansätze und benötigte Eingaben auf, darunter Simplified Solis und Bird.
ASHRAE, REST2 oder spektrale Modelle sind eigene Modellfamilien; eine Erwähnung in
der Forschung macht sie nicht zu einer verwendeten Adaptive-Solar-Komponente.
Ein Wechsel braucht zeitlich vergleichbare Eingaben und eine separate Bewertung.

## 2. NWP-basierte Strahlungsprognosen

Numerische Wettermodelle prognostizieren atmosphärische Zustände und Strahlung.
Wolkenlage, räumliches Raster, Ausgabezeit und Modellparametrisierung bestimmen die
Eignung vor Ort. Ein physikalischer PV-Umrechner kann einen verschobenen Wolkenforecast
nicht automatisch korrigieren.

### 2.1 ECMWF IFS und weitere globale Modelle

[ECMWF Open Data](https://www.ecmwf.int/en/forecasts/datasets/open-data) beschreibt
die aktuell offenen Produkte, Raster und Lizenzbedingungen. Modellinterne
Auflösung, ausgeliefertes Produktraster und Providerinterpolation sind verschiedene
Größen. Eine aus einem Modellnamen abgeleitete lokale Genauigkeitszusage fehlt.

### 2.2 ICON, GFS und regionale Modelle

[DWD Open Data](https://opendata.dwd.de/) und die
[Open-Meteo-Modellübersicht](https://open-meteo.com/en/docs) sind Ausgangspunkte für
konkrete Produkte. ICON-D2, ICON-EU und globale Modelle können unterschiedliche
Horizonte liefern. Adaptive Solar rechnet die gültig verfügbaren Mitglieder, ohne
deren letzte Werte zur künstlichen Horizontverlängerung fortzuschreiben.

HARMONIE oder andere regionale Modelle bleiben mögliche externe Forschungsquellen.
Die tatsächlich auswählbaren UI-Vorgaben und die Möglichkeit eigener Modellkennungen
stehen in der [Bedienung](docs/bedienung.md#2-schritt-standort).

Die [vertiefte Wettermodellrecherche vom 28.10.2026](docs/wettermodelle-und-prognosehorizonte.md)
vergleicht konkrete Produkte und Horizonte für die nächsten 24/48 Stunden.
Sie ergänzt die Archivierungsplanung, ohne eine lokale Rangfolge oder eine
produktive Änderung der Modellauswahl zu behaupten.

### 2.3 Strahlungs- und Zeitsemantik

GHI und DHI sind horizontal, DNI bezieht sich auf die zur direkten Strahlung normale
Fläche. Bei passenden Definitionen gilt näherungsweise
$GHI = DNI\cos(\theta_z) + DHI$. Unterschiedliche Mess-/Zeitunterstützung kann die
Bilanzprüfung beeinflussen.

Die von Adaptive Solar verwendeten Open-Meteo-Strahlungswerte bei `t` gehören zu
`[t−1h,t)`. Temperatur, Wind und Bewölkung sind dort Momentanwerte; der Adapter nutzt
zwei gültige Nachbarendpunkte als lineare Mittelpunktnäherung. Das ist kein
beobachtetes Stundenmittel ([Provider-Zeitdefinition](https://open-meteo.com/en/docs#hourly-parameter-definition)).

## 3. Physikalische Transmissions-, Trübungs- und Sonnenstandsmodelle

[pvlib-Sonnenposition](https://pvlib-python.readthedocs.io/en/stable/reference/solarposition.html)
und [Transposition](https://pvlib-python.readthedocs.io/en/stable/reference/irradiance/transposition.html)
liefern zentrale Bausteine. Ein Sonnenstandsmodell sagt keine Bewölkung voraus;
ein Transpositionsmodell rechnet bekannte Strahlung auf die Modulfläche um.

Adaptive Solar verwendet Hay-Davies, nicht das ebenfalls in der Literatur behandelte
Perez-Transpositionsmodell. Es folgen Faiman-Zelltemperatur, PVWatts-DC,
Stringverluste und Dämpfung sowie eine gemeinsame AC-/DC-Ausgangsbegrenzung.
[Temperaturmodelle](https://pvlib-python.readthedocs.io/en/stable/reference/pv_modeling/temperature.html)
und [PVWatts](https://pvlib-python.readthedocs.io/en/stable/reference/generated/pvlib.pvsystem.pvwatts_dc.html)
beschreiben die jeweiligen Annahmen.

Horizontprofile wirken im Projekt auf Direktlicht. Diffuse Himmelsabschirmung,
elektrische Bypass-/Stringeffekte, spektrale Transmission oder ASTMG173-Referenzspektren
werden dadurch nicht automatisch modelliert. Ein strenger binärer Horizont ist
nicht für jeden nahen teilweise verschattenden Gegenstand eine bessere Näherung.

## 4. Satelliten-Nowcasting und Himmelkameras

Satelliten-/Kameraverfahren können Wolkenzustände oder deren Bewegung zur
Kurzfristprognose nutzen. Geeigneter Vorlauf, Bildlatenz, Region und Wartungsaufwand
sind produkt- und standortabhängig. Ein fester allgemeiner Wechselzeitpunkt zwischen
Satellit und NWP lässt sich aus einzelnen Versuchen nicht ableiten.

[CAMS-Strahlungsprodukte](https://atmosphere.copernicus.eu/solar-radiation-services)
und die [Open-Meteo Satellite Radiation API](https://open-meteo.com/en/docs/satellite-radiation-api)
sind eigenständige Angebote. Externe kommerzielle Dienste wie SolarAnywhere oder
Solargis haben eigene Zugangs- und Datenbedingungen; eine Methodenbeschreibung
beweist keinen kostenlosen operativen Zugang.

Adaptive Solar verarbeitet derzeit weder Satellitenbilder noch All-Sky-Kamerabilder.
Seine optionale lokale GHI-Beobachtung ist eine numerische horizontale Strahlung,
kein Wolkenbewegungsmodell. Die zuvor nicht eindeutig identifizierten ASI- und
Utrecht-Fehlerzahlen werden hier nicht als Benchmark weitergeführt.

## 5. Hybridmodelle (NWP + physikalische Korrektur)

Ein Hybrid kann NWP mit PV-Physik und nachträglich trainierter Fehlerkorrektur
verbinden. Adaptive Solar realisiert diese Aufteilung mit lokalen Residuen.
Die [ML-Recherche](solar_ml_research.md) ordnet Alternativen ein; der
[Ensembleüberblick](ensemble_hybrid_solar_forecasting.md) erklärt Kombination und
Unsicherheit mit Methodenprimärquellen.

Eine Literaturerwähnung „NWP+ML verbessert RMSE um 40 %“ ohne bestimmtes Paper,
Datenbasis und Vergleichspolitik ist kein belastbarer quantitativer Befund und
wurde entfernt. Auch ein nachvollziehbarer fremder Versuch wäre keine typische
Branchenverbesserung oder Zusage für den eigenen Standort.

## 6. Vergleich nach Vorhersagehorizont

| Aufgabe | Vergleichskandidaten | Was fair verglichen werden muss |
| --- | --- | --- |
| Sehr kurzfristig | Persistenz, lokaler Power-/GHI-Nowcast, gegebenenfalls Bildverfahren | Messzeit, Latenz, identische Ziele und Quellenlücken |
| Stunden bis Resttag | NWP-Physik, lokale Korrektur, geeignete externe Anbieter | Vollständige Resttagsenergie, gleicher Cutoff und Messpunkt |
| Folgetage | NWP-Physik, prospektive Residuen und Referenzintegrationen | Damaliger Wetterstand, gemeinsame Zielabdeckung und Ausgangsgrenzen |
| Lange Horizonte/Saison | Geeignete Produktläufe und Klimadiagnose | Tatsächliche Verfügbarkeit; keine Rückdatierung späterer Daten |

MAE, RMSE, normalisierte Fehler und Bias beantworten verschiedene Fragen. Prozentwerte
brauchen denselben Nenner; GHI-, DNI- und PV-Leistungsfehler dürfen nicht durch eine
pauschale Umrechnung gleichgesetzt werden. Reanalysis gegen Beobachtungen misst eine
andere Aufgabe als ein rechtzeitig empfangener Day-ahead-Forecast.

## 7. Freie vs. kommerzielle Datenquellen je Modell

Für das Projekt sind Open-Meteo-Wetter, pvlib und optionale lokale HA-Messungen die
implementierten Eingänge. Die eigene Softwarelizenz GPL-3.0-only, die jeweiligen
Bibliothekslizenzen und Wetter-APIbedingungen gelten getrennt. Für alternative
Datenprodukte Tarif, Datenlizenz, Attribution und mögliche Registrierung prüfen.
Aktuelle Zuordnung: [Toolvergleich](solar-prognosemodelle-zusammenfassung.md) und
[Datenquellenleitfaden](solarprognose_datenquellen_feature_engineering.md).

## 8. Quellenliste und Evidenzgrenze

Primärquellen sind direkt an Definitionen, Bibliotheksfunktionen und Produktangeboten
verlinkt. Alte lokale PDFextraktionen unter temporären Pfaden sind kein öffentlicher
Beleg. Neue numerische Literaturresultate nur zusammen mit exakt auffindbarer
Publikation, Datensatz, Zeitraum, Ausgabezeit, Messgrenze und Basislinie ergänzen.

Der [Implementierungsvertrag](docs/implementation-contract.md) dokumentiert das
vorhandene Modell, der [Validierungsplan](docs/validierung.md) dessen noch offenen
realen Vergleich gegen beide Referenzen. Diese Dokumentationskonsolidierung ist
keine neue empirische Messung und kein neuer Modellreview.
