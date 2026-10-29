# Solar-Prognosemodelle und ML-Verbesserungen – Rechercheüberblick

Stand: 26.10.2026. Dieser Überblick verbindet die Quellenrecherche mit dem
aktuellen Projektstand. Er verdichtet die zuvor wiederholten Methodenbeschreibungen;
Einzelheiten stehen in den verlinkten Fachdokumenten. Nicht eindeutig zugeordnete
Prozentgewinne, pauschale Genauigkeitsranglisten und Aufwandsschätzungen wurden
entfernt. Frühere Texte bleiben über die Git-Historie nachvollziehbar.

## Inhaltsverzeichnis

1. [Übersicht](#1-übersicht)
2. [Frei nutzbare Solar-Prognosemodelle](#2-frei-nutzbare-solar-prognosemodelle)
3. [ML-Verbesserungen für Solarprognosen](#3-ml-verbesserungen-für-solarprognosen)
4. [Ensemble-Methoden und hybride Modelle](#4-ensemble-methoden-und-hybride-modelle)
5. [Kostenlose Datenquellen und Feature Engineering](#5-kostenlose-datenquellen-und-feature-engineering)
6. [Bewertungstabelle: Modelle und Ansätze](#6-bewertungstabelle-modelle-und-ansätze)
7. [Empfohlener Stack für private Anwendungen](#7-empfohlener-stack-für-private-anwendungen)
8. [Quellen](#8-quellen)

## 1. Übersicht

Wetterdaten, physikalische PV-Umrechnung, lokale Fehlerkorrektur und Bewertung sind
unterschiedliche Aufgaben. Ein Weatherprovider ist kein vollständiges PV-Modell;
eine Physikbibliothek hat keinen eigenen universellen Prognosefehler. Kostenloser
Zugang bedeutet weder uneingeschränkte Nutzung noch lokale Verarbeitung aller Daten.

Die [Adaptive-Solar-Implementierung](../../README.md) verwendet Open-Meteo, pvlib und
scikit-learn. Ein standortspezifischer Vorsprung gegenüber Helios oder Open-Meteo
Solar ist weiterhin nicht nachgewiesen. Tests, ein externer Code-Review und einzelne
Laufzeitbeobachtungen ersetzen keinen fairen prospektiven Genauigkeitsvergleich.

## 2. Frei nutzbare Solar-Prognosemodelle

Der [Toolvergleich](solar-prognosemodelle-zusammenfassung.md) ordnet Datenanbieter,
PV-Bibliotheken und HA-Integrationen getrennt ein. Für aktuelle Betriebsparameter
gelten die offiziellen Produkt-/Lizenzbedingungen, keine allgemeine Sternebewertung.

| Baustein / Primärquelle | Rolle | Grenze |
| --- | --- | --- |
| [Open-Meteo](https://open-meteo.com/en/docs) | Wetterprognosen mit Solarstrahlung | Freie API nur nichtkommerziell gemäß Anbieterbedingungen |
| [pvlib](https://pvlib-python.readthedocs.io/) | Sonnenposition, Strahlungsumrechnung, Temperatur und PV-Physik | Benötigt passende Eingaben; keine eigene Wetterprognose |
| [Forecast.Solar](https://www.home-assistant.io/integrations/forecast_solar/) | Externer PV-Prognosedienst mit nativer HA-Integration | Funktionen abhängig vom Tarif und den Eingangsdaten |
| [Solcast](https://www.solcast.com/free-rooftop-solar-forecasting) | Externer PV-Prognosedienst mit privatem Angebot | Wohnstandortprüfung, begrenzte Anfragen und eigene Datenbedingungen |
| [Open-Meteo Solar](https://github.com/rany2/ha-open-meteo-solar-forecast) | Alternative HA-Integration | Eigene Physik-/Konfigurationsannahmen; keine allgemeine Güterangfolge |

## 3. ML-Verbesserungen für Solarprognosen

[ML-Methoden](solar_ml_research.md) behandelt LSTM/GRU, Boosting, Random Forest,
CNN, Transformer, statistische Zeitreihenmodelle, NWP-Hybride und Feature Engineering.
Direkte Methodenquellen sind dort an den Aussagen verlinkt. Modellgröße, publizierter
R²-Wert oder ein Benchmark einer anderen Anlage begründen keine lokale Auswahl.

Im Projekt ist ein Gradient-Boosting-Residualmodell implementiert, getrennt nach
Ausgangsstufe und NWP-/GHI-Regime. LightGBM, XGBoost, CNN, LSTM und Transformer
sind keine automatisch aktivierten Alternativen. Ihre Einführung wäre eine eigene
Code-/Modelländerung mit neuer Abhängigkeits- und Feldprüfung.

## 4. Ensemble-Methoden und hybride Modelle

Der [Ensembleüberblick](ensemble_hybrid_solar_forecasting.md) erklärt Bagging,
Boosting, Stacking, PINNs, Transfer Learning, Unsicherheit und Online Learning.
Adaptive Solar mittelt derzeit gültige Wettermitglieder arithmetisch und addiert
nur bei belegter Lernunterstützung eine Residualkorrektur. Es gibt weder gelerntes
Wetterstacking noch eine Ensemble-Spread-Kalibrierung.

Unsicherheitsverfahren brauchen geeignete separate Kalibrierung. Klassische
Conformal-Coverage setzt passende Annahmen voraus; serielle PV-Daten oder neue
Wetterregime erfüllen diese nicht automatisch. Ein empirisches Fehlerband ist
keine zugesicherte P10/P90-Abdeckung zukünftiger Kurven.

## 5. Kostenlose Datenquellen und Feature Engineering

Der [Datenquellenleitfaden](solarprognose_datenquellen_feature_engineering.md)
trennt Wetterforecast, einzelne archivierte Läufe, Reanalysis, Satellitenprodukte
und originale PV-Messung. Insbesondere ist die Historical Forecast API eine
zusammengesetzte Zeitreihe kurzer Laufanfänge, kein beliebiger historischer
Day-ahead-Stand. Das aktuelle Angebot nennt modellabhängige Abdeckung ungefähr ab 2022.

Sonnengeometrie und Saison sind zum Zielzeitpunkt berechenbar. Wetter und Mess-Lags
brauchen dagegen belegte Ausgabe-/Empfangszeiten. Nachträgliche Füllung fehlender
Messenergie mit Physik würde die Lern-/Benchmarkreferenz verändern und ist im
qualifizierten Projektpfad nicht zulässig. Beide DST-Wechsel und die tatsächlichen
UTC-Dauern lokaler Tage gehören zur Prüfung.

## 6. Bewertungstabelle: Modelle und Ansätze

| Ansatz | Was ein Versuch prüfen muss | Aktueller Projektstand |
| --- | --- | --- |
| Physik | Richtige Module, Wettervintage, Ausrichtungen, Messgrenze und gemeinsame Begrenzung | Implementierte Baseline |
| Lokale Residuen | Chronologie, qualifizierte Labels, neue Zieltage, Bias und belegte Leadbereiche | Implementiert, produktive Qualifikation offen |
| Wettergewichtung/Stacking | Gleiche Inputs und Ziele, separate Auswahl-/Prüftage, Missing-Data-Politik | Forschungskandidat |
| Neue Lag-/Clearnessfeatures | Tatsächliche Verfügbarkeit und abgetrennte Ablation | Forschungskandidat |
| Tiefe Netze/Transfer | Datenunterstützung, Fremddomäne, Ressourcen und Binärkompatibilität | Kein Projektfeature |
| Quantile/Conformal | Kalibrierung, zeitliche Abhängigkeit und zukünftige Coverage | Kein zertifizierter Projektpfad |
| Externer Gütevergleich | Vollständige gepaarte Tage je Stufe/Horizont gegen beide Referenzen | Noch offen |

MAE, RMSE und normalisierter RMSE werden nicht gleichgesetzt. Prozentmetriken brauchen
einen definierten Nenner; Strahlung in W/m² ist nicht Erzeugungsleistung in W oder
Tagesenergie in kWh. Nachtfilter, Datenlücken und Abregelung getrennt ausweisen.

## 7. Empfohlener Stack für private Anwendungen

Für dieses Repository zuerst die bereits vorhandene Kombination aus Open-Meteo,
pvlib, lokalen Residuen und nativer HA-Persistenz verwenden und qualifizieren.
Es werden weder zusätzliche Datenbankserver noch Cronjobs oder ein FastAPI-Dienst
benötigt. Konkrete Schritte: [Installation](../anwendung/installation.md),
[Bedienung](../anwendung/bedienung.md), [Entwicklung](../entwicklung/entwicklung.md).

Danach Kandidaten einzeln gegen die unveränderte Politik vergleichen. Refitkosten
zunächst messen; ein Throttle kann die Modellaktualität verändern. Zusätzliche
Modelle oder gelockerte Qualitätsgates sind keine sichere Standardoptimierung.
Auswahlkriterien und Hauptperiode vor Sichtung der Ergebnisse einfrieren.
[Validierungsplan](../entwicklung/validierung.md).

## 8. Quellen

Primärquellen stehen direkt in Abschnitt 2 sowie in den drei Methoden-/Datenleitfäden.
Die physikalische Vertiefung steht in
[Strahlung und NWP](solarstrahlungsprognose_recherche.md). Maßgeblich für tatsächlich
implementierte Parameter und Grenzen ist der [Implementierungsvertrag](../technik/implementation-contract.md).
Die [Codeanalyse](adaptive-solar-analyse.md) trennt Fakten von möglichen Versuchen.
Keine allgemein erwartbaren Verbesserungsprozente oder Implementierungsfristen
werden aus fremden Benchmarks übernommen.
