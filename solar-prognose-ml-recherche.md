# Solar-Prognosemodelle und ML-Verbesserungen – Umfassende Recherche

> Umsetzung ab 24.10.2026: [Adaptive Solar](README.md). Literaturmetriken in dieser Recherche sind kein Genauigkeitsnachweis für die neue Implementierung; siehe [Validierungsplan](docs/validierung.md).

> **Stand:** Oktober 2026 | **Fokus:** Nur privat kostenlos nutzbare Ressourcen (Open Source, kostenlose Tiers, öffentliche Daten)
> **Projekt:** prognosemodelle

---

## Inhaltsverzeichnis

1. [Übersicht](#1-übersicht)
2. [Frei nutzbare Solar-Prognosemodelle](#2-frei-nutzbare-solar-prognosemodelle)
3. [ML-Verbesserungen für Solarprognosen](#3-ml-verbesserungen-für-solarprognosen)
4. [Ensemble-Methoden und hybride Modelle](#4-ensemble-methoden-und-hybride-modelle)
5. [Kostenlose Datenquellen und Feature Engineering](#5-kostenlose-datenquellen-und-feature-engineering)
6. [Bewertungstabelle: Modelle und Ansätze](#6-bewertungstabelle-modelle-und-ansätze)
7. [Empfohlener Stack für private Anwendungen](#7-empfohlener-stack-für-private-anwendungen)
8. [Quellen](#8-quellen)

---

## 1. Übersicht

Diese Recherche fasst frei nutzbare Solar-Prognosemodelle, ML-Verbesserungen, Ensemble-Methoden und Datenquellen zusammen. Alle Ressourcen sind für private Nutzung kostenlos (Open Source, kostenlose API-Tiers oder öffentliche Daten). Kommerzielle APIs ohne kostenlosen Tier und lizenzierte Modelle wurden ausgeschlossen.

**Kernergebnis:** Der beste kostenlose Stack für private Solarprognosen besteht aus **Open-Meteo (Daten) + pvlib (Physik) + LightGBM/XGBoost (ML) + Conformal Prediction (Unsicherheit)**. Dieser Stack ist vollständig kostenlos, lokal betreibbar und erreicht R² ~0,90–0,95 bei stündlicher Vorhersage.

---

## 2. Frei nutzbare Solar-Prognosemodelle

### 2.1 Open-Meteo (Weather & Solar Forecast API)

**Beschreibung:** Open-Source-Weather-API (AGPLv3), kostenlos für nicht-kommerzielle Nutzung. Liefert Wettervorhersagen aus über 15 nationalen Wetterdiensten (ECMWF, DWD, NOAA, Météo-France, JMA, KMA, KNMI, DMI, MeteoSwiss, UK Met Office, BOM, CMA, GeoSphere Austria). Daten unter CC BY 4.0.

**Solar-Variablen:** GHI, DNI, DHI, GTI (geneigte Module), Clear-Sky-Strahlung, TOA-Strahlung. Plus Temperatur, Wind, Bewölkung, Niederschlag.

**Zusätzliche Endpunkte:**
- **Satellite Radiation API:** Echtzeit-Solarstrahlung aus Satellitendaten (EUMETSAT MSG/MTG, Himawari-9, SARAH3), 2,5–5 km Auflösung, 10–30 min zeitlich.
- **Historical Weather API:** ERA5-Reanalysis (1940–heute), gap-free global grid, für Bias-Korrektur und ML-Training.
- **Historical Forecast Archive:** Seit 2021, gleiche Formate wie Live-API.

**Modelltyp:** Deterministische NWP-Modelle (kein eigenes PV-Leistungsmodell; Benutzer berechnet PV-Leistung selbst, z. B. mit pvlib).

**Auflösung:** 1–2 km (regional) bis 9–11 km (global). Update: 6 h (global), 1–3 h (regional). Horizont: bis 16 Tage. 15-min-Daten für Zentraleuropa/Nordamerika.

**Kosten/Lizenz:** Kostenlos (10.000 Calls/Tag, non-commercial). Kein API-Key nötig. Daten CC BY 4.0. Server-Code AGPLv3 (Self-Hosting für unbegrenzte Calls möglich).

**Links:** https://open-meteo.com | https://github.com/open-meteo/open-meteo

---

### 2.2 Forecast.Solar

**Beschreibung:** RESTful API-Dienst für Solarproduktions- und Wettervorhersagedaten. Kombiniert historische Bestrahlungsdaten aus PVGIS (JRC der EU-Kommission) mit Wettervorhersagen (Wunderground, OpenWeatherMap, AerisWeather, DWD, MET Norway).

**Modelltyp:** Empirisches/statistisches Modell (kein reines ML). Berücksichtigt Standort, Neigung, Azimut, Dämpfungsfaktor. Anpassung durch tatsächliche Messwerte möglich.

**Horizont:** Bis zu 7 Tage. Rate-limitiert im Free-Tier.

**Genauigkeit:** Keine publizierten MAE/RMSE. Community: oft als "weniger genau" als Solcast und Open-Meteo-basierte Lösungen wahrgenommen, insbesondere bei bewölktem Wetter.

**Kosten/Lizenz:** "Public"-Tier kostenlos (rate-limited, kein API-Key). Höhere Tiers kostenpflichtig.

**HA-Integration:** Eingebaut in Home Assistant.

**Links:** https://forecast.solar | https://doc.forecast.solar

---

### 2.3 pvlib-python

**Beschreibung:** Community-entwickelte Python-Toolbox (BSD-3) für PV-Simulation. Bietet Solare Positionsberechnung, Clear-Sky-Modelle, PV-System-Modellierung (Modul, Inverter, Array), Wettervorhersage-Integration (NOAA GFS, NAM, RAP, HRRR) und PV-Leistungsprognosen aus Wettervorhersagen.

**Modelltyp:** Physikalisches Modell (strahlungsbasiert). Pipeline: Wettervorhersage → Solarposition → Bestrahlung auf Modulebene (POA) → PV-Leistung. Unterstützt verschiedene Modul-/Inverter-Modelle (SAPM, PVWatts, etc.). Kombinierbar mit ML-Modellen.

**Genauigkeit:** Abhängig von Wettervorhersagequalität und Parametrisierung. Typisch MAE 10–20% der Nennleistung (gut parametrisiert).

**Kosten/Lizenz:** Open Source (BSD-3), kostenlos, auch kommerziell. `pip install pvlib`.

**Links:** https://pvlib-python.readthedocs.io | https://github.com/pvlib/pvlib-python

---

### 2.4 Solcast (Free Tier)

**Beschreibung:** Kommerzieller Solar-Datenanbieter mit hochauflösenden Solarstrahlungs- und PV-Leistungsprognosen (Satellitenbilder + NWP). Free Tier: bis zu 10 API-Anfragen/Tag, erfordert Verifizierung der Wohnadresse.

**Modelltyp:** Satellitenbasiert + NWP (proprietär). Nutzt geostationäre Satellitenbilder (real-time cloud tracking) + NWP. Liefert PV-Leistungsprognosen direkt.

**Genauigkeit:** Sehr genau (Community: "Referenzstandard unter kostenlosen Optionen"). Bankable Datenqualität. Keine publizierten MAE/RMSE für Free Tier.

**Kosten/Lizenz:** Free Tier: 10 Calls/Tag (verifizierte Wohnadresse). Enterprise-Pläne für höhere Volumina.

**HA-Integration:** Custom Component (HACS).

**Links:** https://solcast.com/free-rooftop-solar-forecasting | https://docs.solcast.com.au

---

### 2.5 OpenWeatherMap

**Beschreibung:** Kostenlose Wetter-API (1.000 Calls/Tag im Free Tier). **Keine** dedizierte Solar-Irradiance-API im kostenlosen Tier. Solar-Irradiance-API ist Premium/kostenpflichtig.

**Modelltyp:** Wettervorhersage-Modell (kein PV-Leistungsmodell). Keine Solarstrahlungsdaten im Free Tier.

**Kosten/Lizenz:** Free Tier: 1.000 Calls/Tag (Wetterdaten, keine Solarstrahlung). Solar Irradiance API kostenpflichtig.

**Empfehlung:** Nicht für kostenlose Solar-Prognose geeignet. Open-Meteo als Ersatz.

**Links:** https://openweathermap.org | https://openweathermap.org/price

---

### 2.6 Open-Source Solar-Forecast-Projekte auf GitHub

#### 2.6.1 Open-Source Quartz Solar Forecast (Open Climate Fix)

**Beschreibung:** Open-Source PV-Prognose auf Site-Level. Liefert PV-Leistungsprognosen (kW) für 0–48 Stunden für eine einzelne PV-Anlage.

**Modelltyp:**
- **Gradient Boosting Model (Standard):** Nutzt GFS/ICON/ECMWF NWP-Daten (9 Variablen: Visibility, Wind, Temperatur, Niederschlag, Strahlung, Bewölkung etc.)
- **XGBoost Model:** Nutzt Open-Meteo-Variablen (Temperatur, Feuchtigkeit, Taupunkt, Niederschlag, Luftdruck, Bewölkung, Wind, Strahlung etc.)

**Trainiert auf:** 25.000 PV-Anlagen mit über 5 Jahren PV-Historie (UK-Daten).

**Genauigkeit:** Gradient Boosting: MAE 0,19 kW (0–48h), MAE 13,0% der Nennleistung (ohne Nachtstunden). XGBoost: MAE 0,12 kW (gesamt), MAE 0,21 kW (ohne Nachtstunden).

**Einschränkung:** Nur auf UK-Daten trainiert; Anwendung auf andere Regionen mit Vorsicht.

**Kosten/Lizenz:** MIT-Lizenz, kostenlos. `pip install quartz-solar-forecast`.

**Links:** https://github.com/openclimatefix/open-source-quartz-solar-forecast | https://pypi.org/project/quartz-solar-forecast/

---

#### 2.6.2 rany2/open-meteo-solar-forecast

**Beschreibung:** Python-Modul, das Open-Meteo-Daten nutzt, um Solarproduktionsprognosen zu berechnen. Basiert auf pvlib-Methodik (Strahlung → PV-Leistung).

**Features:** Multi-Array (verschiedene Neigungen/Azimute), Multi-Inverter, Horizont-Shading, Partial Shading (experimentell), Snow-Coverage-Modell, Tracking (Azimut/Tilt/Dual), 15-min-Auflösung.

**Genauigkeit:** Abhängig von Open-Meteo-Datenqualität und Parametrisierung (keine publizierten Benchmarks).

**Kosten/Lizenz:** MIT-Lizenz, kostenlos. `pip install open-meteo-solar-forecast`.

**Links:** https://github.com/rany2/open-meteo-solar-forecast | https://github.com/rany2/ha-open-meteo-solar-forecast

---

#### 2.6.3 Weitere GitHub-Projekte

| Projekt | Beschreibung | Link |
|---------|-------------|------|
| **Solar-Forecast-ML** (Zara-Toorox) | Lokales AI-Solar-Forecast für HA (Attention Transformer), vollständig lokal | https://github.com/Zara-Toorox/Solar-Forecast-ML |
| **smart-persistence-model** (Felix561) | Python-Implementierung des Smart Persistence Model für Kurzzeit-PV-Prognose | https://github.com/Felix561/smart-persistence-model |
| **ha-pvnode** (darwindaume) | Home Assistant PV-Node-Integration | https://github.com/darwindaume/ha-pvnode |
| **PVForecast** (StefaE) | PV-Prognose zur Optimierung des Stromverbrauchs, Integration mit solaranzeige | https://github.com/StefaE/PVForecast |
| **fmi-open-pv-forecast** (fmidev) | Wettervorhersage-bewusste PV-Prognose (nicht mehr gepflegt) | https://github.com/fmidev/fmi-open-pv-forecast |
| **climate-aware-pv-forecasting** (Jouqio) | Klimabewusste PV-Prognose | https://github.com/Jouqio/climate-aware-pv-forecasting |

---

#### 2.6.4 Solar Forecast Arbiter (EPRI)

**Beschreibung:** Open-Source-Plattform für den Austausch und die Bewertung von Solarprognosen. Bietet REST-API für Daten-Upload und -Vergleich. Wird hauptsächlich für Forschung und Benchmarking genutzt.

**Links:** https://forecastarbiter.epri.com

---

### 2.7 Home Assistant Integrationen für Solar-Prognose

| Integration | Beschreibung | Kosten | Quelle |
|-------------|-------------|--------|--------|
| **Solcast** (Custom Component / HACS) | Nutzt Solcast-API für PV-Leistungsprognosen, automatisches PV-Tuning, History, adaptive Shading-Dämpfung | Free Tier (10 Calls/Tag) | https://github.com/BJReplay/ha-solcast-solar |
| **Forecast.Solar** (Eingebaut) | Offizielle HA-Integration, einfache Konfiguration, kein API-Key für Public-Tier | Free (rate-limited) | https://www.home-assistant.io/integrations/forecast_solar/ |
| **Open-Meteo Solar Forecast** (Custom Component / HACS) | Basiert auf Forecast.Solar-Integration, nutzt Open-Meteo-API, oft als genauer wahrgenommen | Kostenlos | https://github.com/rany2/ha-open-meteo-solar-forecast |
| **Solcast Solar Enhanced** (Add-on) | Companion-Add-on für Solcast mit erweiterten Features (History, PV-Tuning, adaptive Dämpfung) | Free Tier | HA-Community |
| **Solar-Forecast-ML** (Custom Integration) | Lokales AI-Solar-Forecast (Attention Transformer), vollständig lokal, keine Cloud-Abhängigkeit | Kostenlos (Open Source) | https://github.com/Zara-Toorox/Solar-Forecast-ML |

---

## 3. ML-Verbesserungen für Solarprognosen

### 3.1 LSTM / GRU für PV-Ertragsprognose

**Beschreibung:** Rekurrente neuronale Netze (RNNs) für Zeitreihen. Erfassen langfristige Abhängigkeiten in historischen Ertrags- und Wetterdaten durch Gating-Mechanismen (Forget/Input/Output-Gates bei LSTM; Reset/Update-Gates bei GRU).

- **GRU:** Vereinfacht (weniger Parameter), schnelleres Training, oft vergleichbare Ergebnisse wie LSTM.
- **LSTM:** Komplexer, genauer bei sehr langen Sequenzen.
- Typische Anwendung: 15-min bis 24-h-Vorhersagen.

**Genauigkeitsverbesserung:** LSTM vs. Persistence: +20–35% (nRMSE). RMSE-Verbesserung ~8% gegenüber traditionellen ML-Modellen. Studie (MDPI 2023, 193 Zitationen): LSTM schlägt MLP und physikalische Modelle; CNN-LSTM-Hybrid noch besser.

**Datenanforderungen:** Historische PV-Leistung (min. 1 Jahr, ideal 2–3 Jahre, 15-min oder stündlich). Wetterdaten: Irradianz (GHI/DNI), Temperatur, Bewölkung, Wind, Luftfeuchtigkeit. Mindestens 10.000–50.000 Datenpunkte.

**Implementierungsaufwand:** Mittel bis Hoch (Hyperparameter-Tuning, GPU empfohlen, Daten-Pipeline, Normalisierung, Sliding-Window-Sequenzen).

**Bibliotheken:** TensorFlow/Keras, PyTorch, scikit-learn (Vorverarbeitung).

**GitHub/Papers:** IntechOpen 2020 (157 Zit.), MDPI Energies 2023 (193 Zit.), SOLETE-Plattform: https://github.com/DVPombo/SOLETE

---

### 3.2 XGBoost / LightGBM / CatBoost für Solar

**Beschreibung:** Gradient-Boosting-Tree-Ensembles. Besonders gut mit strukturierten Wetter- und Zeit-Features. Robust gegen nicht-lineare Beziehungen und Interaktionen.

- **LightGBM:** Schnell, speichereffizient, gut für große Datensätze.
- **XGBoost:** Hohe Genauigkeit, oft bester Einzelmodell-Performer.
- **CatBoost:** Exzellent bei kategorialen Features (z. B. Wetterzustände), wenig Hyperparameter-Tuning nötig.

**Genauigkeitsverbesserung:** XGBoost in direktem Vergleich (2024, 12 Zitationen) genauestes Modell, gefolgt von LightGBM; LSTM schlechter. LightGBM: R² bis 0,9984 (MSE 2,41). Verbesserung gegenüber Random Forest: deutlich. Verbesserung gegenüber Persistence: typisch 15–30% nRMSE-Reduktion.

**Datenanforderungen:** Tabellarische Features: Zeit (Stunde, Monat, Tag des Jahres), Wetter (Irradianz, Temperatur, Bewölkung, Wind), historische Erträge. Mindestens 1–2 Jahre stündliche Daten. Keine Sequenzstruktur nötig.

**Implementierungsaufwand:** Niedrig bis Mittel (scikit-learn-ähnliche API, schnelles Training in Minuten, wenig Tuning).

**Bibliotheken:** `xgboost`, `lightgbm`, `catboost` (alle pip-installierbar, MIT/Apache). scikit-learn (Preprocessing, CV, Metriken).

**GitHub/Papers:** ScienceDirect 2023 (111 Zit.), Nature 2026 (Stacked Gradient Boosting–XGBoost Ensemble), Kaggle "Forecasting Solar Power: XGBoost vs LSTM".

---

### 3.3 Random Forest für PV-Leistung

**Beschreibung:** Ensemble aus vielen Entscheidungsbäumen auf Bootstrap-Samples. Robust, wenig Overfitting, eingebaute Feature-Importance.

**Genauigkeitsverbesserung:** R² typisch 0,90–0,95 bei stündlicher PV-Leistung. Suncast-Modell (Hugging Face, PyCaret AutoML): MAE 76 W/m², RMSE 127 W/m², R² 0,748, MAPE 1,49%. PVOD-Datensatz: RF R² 0,952, MAE 0,516 (nach Feature-Selection). Gute Baseline, aber oft von Boosting-Modellen übertroffen.

**Datenanforderungen:** Tabellarisch, 1 Jahr+ stündliche Daten. Weniger Daten nötig als Deep Learning.

**Implementierungsaufwand:** Niedrig (scikit-learn `RandomForestRegressor`, schnelles Training).

**Bibliotheken:** scikit-learn (`RandomForestRegressor`), PyCaret (AutoML), joblib.

**GitHub/Papers:** github.com/harryman-dev/solar-forecast (RF, DWD MOSMIX, FHEM/MQTT), github.com/canberkkacan/PV-Panel-Power-Generation-Forecast-with-Random-Forest (R² 0,939), Hugging Face: ryukkt62/Suncast.

---

### 3.4 CNN für Strahlungsprognose

**Beschreibung:** Convolutional Neural Networks extrahieren räumliche Features aus Bildern (Himmelkameras, Satellitenbilder) und sind ideal für Wolkenbewegung und Strahlungsprognose (GHI/DNI). 1D-CNNs auch für Zeitreihen-Muster.

- **SolarNet:** 20-schichtiges CNN, nur Himmelbilder als Input, 8,85% nRMSE, 25,14% Forecast Skill Score.
- **C-GHI:** CNN + Satellitenbilder, bis 26% Verbesserung gegenüber Persistence (day-ahead).
- **CNN-LSTM Hybrid:** CNN extrahiert räumliche, LSTM zeitliche Features → beste Performance bei Strahlung.

**Genauigkeitsverbesserung:** Intra-hour (10–60 min): 20–39% Forecast Skill über Persistence. Day-ahead: bis 26% Verbesserung. CNN-LSTM: bestes Modell in MDPI-Review (RMSE 8,19 W/m² bei Ghimire et al.). CNN-1D: RMSE 36,24 W/m² bei 10-min-Horizont, +11% vs. Persistence.

**Datenanforderungen:** Bild-Daten: Himmelkamera-Aufnahmen oder Satellitenbilder (GOES, MSG). Oder Zeitreihen rekonstruiert als 2D-Matrizen. Mindestens 6 Monate bis 6 Jahre Daten.

**Implementierungsaufwand:** Hoch (GPU erforderlich, Bild-Pipeline, viel Speicher, Hyperparameter-Tuning).

**Bibliotheken:** TensorFlow/Keras, PyTorch, OpenCV, PIL, scikit-image.

**GitHub/Papers:** MDPI Energies 2020 (Review), ScienceDirect 2020 (CNN-LSTM, 34 Standorte, 3 Klimazonen), OSTI 2022 (Sky Image Sequences).

---

### 3.5 Transformer-basierte Modelle (Informer, Autoformer) für Solar

**Beschreibung:** Transformer-Modelle nutzen Self-Attention-Mechanismen für lange Zeitreihen (LSTF). Spezielle Varianten für Solar:

- **Informer:** ProbSparse Self-Attention, reduziert Zeit-/Speicherkomplexität, one-shot Long-Sequence-Prediction.
- **Autoformer:** Auto-Korrelation statt Self-Attention, Seriendekomposition (Trend + Saisonalität).
- **DTCformer:** Temporal Convolution + Autoformer + DILATE-Loss, +5–42% Verbesserung bei 24/48/72-h-Vorhersagen.
- **CEEMDAN-Informer:** Signaldekomposition + Informer, -30,88% Fehler gegenüber reinem Informer.

**Genauigkeitsverbesserung:** D-Informer: -67,64% MSE, -49,58% MAE, -43,43% RMSE gegenüber Baselines, R² bis 0,9917 (Winter). CEEMDAN-Informer: Fehlerindex -30,88% vs. single Informer. Vanilla Transformer schlägt Informer und Autoformer in einer Studie (2024, Hubei, China). DTCformer: +5–42% DILATE-Verbesserung.

**Datenanforderungen:** Lange Zeitreihen (mehrere Jahre), multivariate Inputs (Irradianz, Temperatur, Wind, historische Leistung). Stündliche oder 15-min-Auflösung.

**Implementierungsaufwand:** Hoch (komplexe Architekturen, viel GPU-Speicher, Hyperparameter-Tuning).

**Bibliotheken:** PyTorch, `transformers` (Hugging Face), Informer-Repo (thuml/Informer2020), Autoformer-Repo.

**GitHub/Papers:** DOI 10.1016/j.solcom.2024.100089 (vanilla Transformer, Informer, Autoformer), Frontiers in Energy Research 2023 (Informer), Energies 2025 (DTCformer), arxiv 2408.00601 (AutoPV).

---

### 3.6 Zeitreihen-Modelle (Prophet, ARIMA, SARIMA) für PV

**Beschreibung:** Klassische statistische Zeitreihen-Modelle:

- **ARIMA:** Modelliert Autokorrelation und Trend.
- **SARIMA:** Erweitert ARIMA um saisonale Komponenten (täglich, wöchentlich, jährlich).
- **Prophet (Meta):** Additiver Trend + Saisonalität + Feiertage, robust bei fehlenden Daten, automatische Changepoint-Erkennung.

**Genauigkeitsverbesserung:** SARIMA: gut für saisonale Muster. Prophet: MAPE 2,2–24,2% je nach Kontext. ARIMA: ARIMA(4,0,1) für US-Solar-Output (12-Monats-Forecast). SARIMA-Kalman-Hybrid: -59,3% Fehler bei Solarstrahlung, -75% bei Temperatur. In direktem Vergleich: LSTM oft besser bei nicht-linearen Mustern; Prophet/ARIMA besser bei Interpretierbarkeit und kleinen Daten.

**Datenanforderungen:** Univariate oder multivariate Zeitreihen, min. 1–2 Jahre historische Daten. Prophet robust bei Lücken; ARIMA/SARIMA benötigen regelmäßige Daten.

**Implementierungsaufwand:** Niedrig (`statsmodels` (ARIMA/SARIMA), `prophet` (pip), einfache API).

**Bibliotheken:** `statsmodels` (ARIMA, SARIMA, SARIMAX), `prophet` (Meta), `pmdarima` (auto-ARIMA).

**GitHub/Papers:** github.com/aokdata/Solar_Power_Output_Time_Series (ARIMA + Prophet), Preprints 2026 (Comparative Study), Springer 2025 (78 Zit.), ScienceDirect 2025 (SARIMA-Kalman).

---

### 3.7 Hybride Modelle (NWP + ML)

**Beschreibung:** Kombination von Numerical Weather Prediction (NWP) mit Machine Learning. NWP liefert meteorologische Vorhersagen (Irradianz, Temperatur, Bewölkung), ML lernt die nicht-lineare Abbildung auf PV-Leistung.

Varianten:
- **NWP + XGBoost/LightGBM:** Tabellarisch, schnell, sehr genau.
- **NWP + LSTM/GRU:** Sequentiell, erfasst zeitliche Dynamik.
- **NWP + CNN-LSTM:** Spatiotemporal (Wolkenfelder).
- **NWP + Ensemble:** Random Forest + XGBoost Quantile Regression für probabilistische Vorhersagen.
- **Model-Agnostic Hybrid:** Mehrere NWP-Modelle + ML-Korrektur.

**Genauigkeitsverbesserung:** Mayer et al. 2022 (629 Zitationen): 24 ML-Modelle für day-ahead PV-Forecasting auf NWP-Basis verglichen. Asiedu et al. 2024 (79 Zitationen): Hybrid-Modelle übertreffen Single-Modelle. NWP+ML typisch 10–25% besser als reine NWP oder reine ML.

**Datenanforderungen:** NWP-Daten (kostenlos: ECMWF, DWD ICON, NOAA GFS/HRRR, Open-Meteo). Historische PV-Leistung (min. 1 Jahr). Standort-spezifische Kalibrierung.

**Implementierungsaufwand:** Mittel bis Hoch (NWP-Daten-Pipeline, Feature-Engineering, Modell-Training, Ensemble-Management).

**Bibliotheken:** pvlib (PV-Modellierung), Herbie (NOAA-Daten), xarray, pandas, scikit-learn, XGBoost/LightGBM.

**GitHub/Papers:** github.com/williamhobbs/solar-fleet-forecast-probability-tool (XGBoost/RF Quantile, HRRR/GEFS, BSD-3), arxiv 2112.04963 (Model-Agnostic Hybrid NWP+ML), ScienceDirect 2022 (Mayer et al.).

---

### 3.8 Feature Engineering

**Beschreibung:** Die Qualität der Features ist oft wichtiger als das Modell. Wichtige Feature-Kategorien:

**Zeit-Features:**
- Stunde, Monat, Tag des Jahres, Wochentag
- Zykliche Kodierung (sin/cos) für Stunde/Monat
- Sonnenstand (Azimut, Elevation, Zenith) via pvlib

**Wetter-Features:**
- GHI, DNI, DHI (Strahlung)
- Temperatur (Luft, Modul), Windgeschwindigkeit, Luftfeuchtigkeit, Bewölkung
- Historische Irradianz (Lags: 1h, 2h, 24h)

**PV-spezifische Features:**
- Klarheitsindex (Clear Sky Index, CSI)
- Clear-Sky-Strahlung (pvlib)
- Historische Erträge (Lags, Rolling Means)

**Genauigkeitsverbesserung:** Feature-Engineering kann Modellgenauigkeit um 10–30% verbessern. Zykliche Zeitkodierung: +5–10% vs. rohe Stunden. Clear-Sky-Index: sehr wichtig für Normalisierung. Feature-Selection (Korrelation, SHAP): reduziert Overfitting, verbessert Generalisierung.

**Implementierungsaufwand:** Mittel (pvlib für Sonnenstand/Clear-Sky, pandas für Lags/Rolling, scikit-learn für Scaling).

**Bibliotheken:** `pvlib`, `pandas`, `numpy`, `scikit-learn`, `shap` (Feature-Importance).

**Papers:** Renewable Energy 2024 (Advanced feature engineering), PMC 2025 (Enhancing PV power forecasting), Nature 2026 (Spectral Feature Engineering, FFT).

---

### 3.9 Open-Source ML-Bibliotheken

| Bibliothek | Zweck | Lizenz | Python-Paket |
|-----------|-------|--------|-------------|
| scikit-learn | Klassische ML (RF, GBM, SVM, Preprocessing) | BSD-3 | `scikit-learn` |
| XGBoost | Gradient Boosting | Apache-2.0 | `xgboost` |
| LightGBM | Gradient Boosting | MIT | `lightgbm` |
| CatBoost | Gradient Boosting (kategorisch) | Apache-2.0 | `catboost` |
| TensorFlow/Keras | Deep Learning (LSTM, GRU, CNN, Transformer) | Apache-2.0 | `tensorflow` |
| PyTorch | Deep Learning | BSD-3 | `torch` |
| Prophet | Zeitreihen (Meta) | MIT | `prophet` |
| statsmodels | ARIMA/SARIMA | BSD-3 | `statsmodels` |
| pvlib | PV-Modellierung, Sonnenstand, Clear-Sky | BSD-3 | `pvlib` |
| PyCaret | AutoML | MIT | `pycaret` |
| Optuna | Hyperparameter-Optimierung | MIT | `optuna` |
| SHAP | Feature-Importance / Explainability | MIT | `shap` |

---

## 4. Ensemble-Methoden und hybride Modelle

### 4.1 Ensemble-Methoden (Bagging, Boosting, Stacking) für Solar

**Beschreibung:** Ensemble-Methoden kombinieren mehrere Modelle zur Verbesserung der Vorhersagegenauigkeit:

- **Bagging (Bootstrap Aggregating):** Mehrere Modelle auf verschiedenen Bootstrap-Stichproben; Vorhersagen werden gemittelt. Reduziert Varianz (z. B. Random Forest).
- **Boosting:** Modelle sequentiell; jedes korrigiert die Fehler des vorherigen. Reduziert Bias (z. B. XGBoost, LightGBM, CatBoost).
- **Stacking:** Mehrere Modelle parallel; ein Meta-Learner kombiniert ihre Vorhersagen.

**Vorteile:** Deutlich besser als einzelne Modelle; CatBoost/LightGBM outperformen traditionelle Methoden. Robust gegen Overfitting (Bagging). Feature Importance verfügbar (Boosting).

**Nachteile:** Höherer Rechenaufwand beim Training. Komplexere Hyperparameter-Abstimmung. Black-Box bei Stacking.

**Implementierungsaufwand:** Mittel. Standard-ML-Bibliotheken bieten Out-of-the-Box-Implementierungen. Stacking-Ensemble in wenigen Zeilen mit `sklearn.ensemble.StackingRegressor`.

**Tools:** scikit-learn (`RandomForestRegressor`, `GradientBoostingRegressor`, `StackingRegressor`, `VotingRegressor`), XGBoost, LightGBM, CatBoost, skforecast, mlforecast (Nixtla, mit Conformal Prediction).

**Forschung:** SE2GPA (Springer, 2025): Stacked Ensemble aus vier Boosting-Algorithmen. Khan et al. (2022): Deep Ensemble Stacking für PV an verschiedenen Standorten. Nature Scientific Reports (2026): CatBoost und LightGBM outperformen traditionelle Methoden bei 1–24h-Horizonten.

---

### 4.2 Physikalisch-informierte neuronale Netze (PINNs) für PV

**Beschreibung:** PINNs betten physikalische Gesetze (PDEs/ODEs, z. B. Energiebilanz-Gleichungen von PV-Modulen) direkt in die Loss-Funktion des neuronalen Netzes ein. Das Netz lernt aus Daten und physikalischen Constraints (z. B. Temperatur-ODE des Moduls, Strahlungs-Umwandlungsphysik).

**Vorteile:** Vorhersagen respektieren physikalische Gesetze; bessere Extrapolation. Weniger Trainingsdaten nötig als reine DL-Modelle. Bessere Generalisierung auf unbekannte Bedingungen.

**Nachteile:** Komplexe Implementierung der physikalischen Constraints. Physikalische Gleichungen müssen bekannt und korrekt formuliert sein. Training kann instabil sein (Multi-Objektiv-Optimierung). Höherer Rechenaufwand pro Training.

**Implementierungsaufwand:** Hoch (Kenntnisse in Physik und Deep Learning nötig). Frameworks: DeepXDE, NVIDIA Modulus (PhysicsNeMo). pvlib kann zur Constraint-Formulierung genutzt werden.

**Genauigkeit:** MSE-Reduktion bis zu 14,78% (Cong et al.).

**Forschung:** MIPV-NWP-PINN (Copernicus, 2025): Multi-Scale-Framework kombiniert WRF-NWP, GHI-Bias-Korrektur (QM-TPA-LSTM) und PINN-iTransformer. CNN-LSTM-PINNs (Energies, 2026): Hybrides Framework mit räumlichen (CNN) und zeitlichen (LSTM) Abhängigkeiten + physikalische Constraints. PKINN (ScienceDirect, 2026): Photovoltaic Knowledge-Informed Neural Network.

---

### 4.3 Kombination aus NWP und ML

**Beschreibung:** NWP liefert meteorologische Vorhersagen (Strahlung, Temperatur, Wind, Bewölkung). ML-Modelle nutzen diese als Input-Features und korrigieren systematische Fehler (Bias) der NWP-Modelle.

Ansätze:
- **Post-Processing:** ML lernt, NWP-Fehler zu korrigieren (z. B. Quantile Mapping + LSTM).
- **Hybrid:** NWP-Outputs als Features in ML-Modellen (XGBoost, LSTM).
- **Spektral-Nudging (ECMWF):** Kombination von ML-großskaligen Vorhersagen mit NWP-physikalischen Details.

**Vorteile:** ML korrigiert systematische NWP-Bias; bis zu 23% MAE-Reduktion (MIPV-NWP-PINN). Deckt 0–14 Tage ab (NWP-Stärke). Kostenlose NWP-Daten verfügbar (Open-Meteo, ECMWF, NOAA).

**Nachteile:** Abhängig von NWP-Qualität und Verfügbarkeit. NWP-Updates nur alle 6–12 Stunden. Hohe Datenmengen. NWP-Daten-Handling (GRIB, NetCDF) erfordert Spezialwissen.

**Implementierungsaufwand:** Mittel bis Hoch. Open-Meteo bietet einfache REST-API. pvlib und xarray vereinfachen die Verarbeitung.

**Tools:** Open-Meteo API, ECMWF Open Data, NOAA HRRR/GFS, pvlib, xarray, netCDF4, Open Climate Fix (Quartz Solar Forecast).

**Forschung:** ArXiv 2112.04963 (Model-Agnostic Hybrid NWP+ML für Solarprognose in den Tropen). ECMWF Hybrid Forecasting (2025): Spektral-Nudging von IFS (NWP) und AIFS (ML). Solcast: Ensemble aus NWP-Modellen + DL-Korrektur für 4–48h-Fenster.

---

### 4.4 Multi-Model Ensemble (verschiedene Wettermodelle kombinieren)

**Beschreibung:** Kombination von Vorhersagen mehrerer unabhängiger NWP-Modelle (ECMWF IFS, NOAA GFS/HRRR, DWD ICON, MeteoFrance) zu einem probabilistischen Ensemble.

Methoden:
- **Simple Ensemble Mean:** Einfaches Mittel aller Modelle.
- **Weighted Superensemble:** Gewichtung nach historischer Skill.
- **Rank-Histogram Calibration:** Anpassung der Ensemble-Spread an beobachtete Klimatologie.
- **Bias-Korrektur:** Jedes Modell individuell korrigiert, dann kombiniert.

**Vorteile:** Natürliche Unsicherheitsquantifizierung durch Ensemble-Spread. Reduziert Bias einzelner Modelle. Robustere Vorhersagen. Ausfall eines Modells kompensierbar.

**Nachteile:** Höhere Datenmenge und Rechenaufwand. Komplexe Gewichtungsstrategien nötig. Unterschiedliche Auflösungen/Zeitstempel harmonisieren. Monitoring und Wartung mehrerer Pipelines.

**Implementierungsaufwand:** Mittel. Open-Meteo aggregiert bereits mehrere Modelle (ICON, GFS, ECMWF, HRRR). Eigenes Multi-Model-Ensemble erfordert Datensammlung, Harmonisierung und Gewichtung.

**Tools:** Open-Meteo (aggregiert ECMWF, GFS, ICON, HRRR, MeteoFrance), SolarGIS (CMV + 4 NWP-Modelle), Open Climate Fix Quartz, pvlib.

**Forschung:** Solcast: Ensemble aus mesoskaligen + globalen NWP-Modellen + DL-Korrektur. Solargis: Kombination aus Cloud Motion Vector und 4 NWP-Modellen.

---

### 4.5 Transfer Learning für PV-Prognose

**Beschreibung:** Vortrainierte Modelle (z. B. auf großen PV-Datensätzen oder synthetischen PVGIS-Daten) werden auf neue Standorte mit wenig Daten übertragen.

Strategien:
- **Feature Extraction:** Vortrainiertes Modell als Feature-Extractor, nur letzte Schicht neu trainiert.
- **Fine-Tuning:** Gesamtes Modell mit wenigen lokalen Daten nachtrainiert.
- **Domain Adaptation:** Anpassung an unterschiedliche Klimazonen/Technologien.
- **Synthetic → Real:** Training auf PVGIS-synthetischen Daten, Fine-Tuning auf realen Messungen.

**Vorteile:** Funktioniert mit wenig Daten (neue Anlagen, < 1 Jahr). Bis zu 71% schnelleres Training (Tang et al.). Bis zu 69% Verbesserung bei Datenknappheit. Cross-continental Transfer möglich (Bak et al., 2025).

**Nachteile:** Source-Domain muss target-ähnlich sein. Negative Transfer möglich bei zu unterschiedlichen Domänen. Vortrainierte Modelle müssen verfügbar sein. Klima-/Technologie-Unterschiede können schaden.

**Implementierungsaufwand:** Mittel. PyTorch/TensorFlow bieten einfache Transfer-Learning-APIs. Vortrainierte Modelle (SolNet) sind verfügbar.

**Tools:** SolNet (GitHub: Joris-Dprtr/SolNet) – Open-Source Pre-trained DL-Modelle für globale PV-Prognose (PVGIS + Open-Meteo). PyTorch/TensorFlow. Hugging Face Model Hub. gist-ailab/transfer-learning-PV-forecasting (Transformer-basiertes Cross-Region Transfer Learning).

**Forschung:** SolNet (International Journal of Forecasting, 2025): Two-Step-Pipeline mit Transfer Learning von PVGIS-synthetischen Daten. PMC (2022): TL mit Stacked LSTM für PV-Produktionsprognose bei Datenknappheit. Bak et al. (IEEE Access, 2025): Cross-continental Transfer Learning mit 4,5M Datenpunkten. Tang et al. (Renewable & Sustainable Energy Reviews, 2022): 69,51% Genauigkeits- und 71,42% Effizienzverbesserung.

---

### 4.6 Unsicherheitsquantifizierung (Quantile Regression, Conformal Prediction)

**Beschreibung:** Methoden zur Schätzung von Vorhersageintervallen statt nur Punktvorhersagen:

- **Quantile Regression:** Modell wird trainiert, spezifische Quantile (z. B. 10%, 50%, 90%) der Zielverteilung vorherzusagen. Direkt in das Modell integriert.
- **Conformal Prediction:** Post-Processing-Methode, die kalibrierte Vorhersageintervalle mit mathematischer Garantie (Coverage) liefert.
- **Conformalized Quantile Regression (CQR):** Kombination beider Ansätze – Quantile Regression + Conformal-Kalibrierung für schärfere Intervalle.
- **Adaptive Conformal Inference (ACI):** Adaptive Anpassung der Intervalle an nicht-stationäre Daten (z. B. täglicher Reset).

**Vorteile:** Conformal Prediction bietet Coverage-Garantien (z. B. 90%). Quantile Regression in jedes Modell integrierbar. CQR liefert schärfere Intervalle bei gleicher Coverage.

**Nachteile:** Conformal Prediction konservativere Intervalle als reine Quantile-Regression. Quantile-Crossing-Problem (Quantile überlappen sich). Calibration-Set nötig (Datenreduktion). Hyperparameter-Abstimmung der Adaptivität.

**Implementierungsaufwand:** Niedrig bis Mittel. Viele Frameworks bieten Out-of-the-Box-Unterstützung:
- LightGBM/XGBoost: `objective='quantile'` mit `alpha=0.1/0.5/0.9`
- sktime/mlforecast: Conformal Prediction integriert
- NeuralForecast: `PredictionIntervals`-Klasse

**Tools:** mlforecast (Nixtla, Conformal Prediction integriert), NeuralForecast (Nixtla, Quantile + Conformal), LightGBM/XGBoost/CatBoost (Quantile Regression), scikit-learn (`QuantileRegressor`), MAPIE (Conformal Prediction Library), NeuralProphet (Quantile Regression + Conformal Prediction Module).

**Forschung:** MDPI Sustainability (2026): Multi-Scale Temporal-Spatial Attention + CQR für PV. Nature Scientific Reports (2026): ACI mit täglichem Miscoverage-Reset für PV. Nam et al. (ScienceDirect, 2025): Conformal Prediction Techniken für Solarprognose.

---

### 4.7 Online Learning / Adaptive Modelle

**Beschreibung:** Modelle, die kontinuierlich mit neuen Daten aktualisiert werden, statt batchweise neu trainiert zu werden.

Ansätze:
- **Incremental Learning:** Modell wird mit neuen Daten inkrementell aktualisiert (`partial_fit` in scikit-learn).
- **Streaming ML:** Modelle verarbeiten Datenströme in Echtzeit (River, Vowpal Wabbit).
- **Drift Detection:** Erkennung von Konzeptdrift (saisonale Änderungen, Degradation) und automatische Modell-Anpassung.
- **Adaptive Ensembles:** Ensemble-Gewichte werden dynamisch an aktuelle Performance angepasst.

**Vorteile:** Modelle passen sich an aktuelle Bedingungen an (Degradation, saisonale Shifts). Kein großes Retraining nötig. Automatische Anpassung ohne manuelles Eingreifen. Geringere Rechenlast als Batch-Retraining.

**Nachteile:** Risiko von Catastrophic Forgetting. Online-Daten müssen qualitativ hochwertig sein. Komplexes Monitoring nötig (Drift Detection). Online-Updates können instabil sein.

**Implementierungsaufwand:** Mittel bis Hoch. Online-Learning-Frameworks (River) bieten einfache APIs, aber Integration in PV-Pipelines erfordert Daten-Streaming-Infrastruktur.

**Tools:** River (Online ML Library), Vowpal Wabbit (schnelles Online Learning), scikit-learn (`partial_fit`), SolarForecast ML (SFML) – HA-Integration mit adaptive/self-learning Attention Transformer (lokal, privat), OnlineStats.jl (Julia).

**Forschung:** ResearchGate (2026): LSTM-basiertes Online Learning für Echtzeit-Solarprognose. ScienceDirect (2026): Adaptive Dual-Path PV-Forecasting für Echtzeit. SFML v3.0 (HA-Community, 2026): Adaptive Self-Learning für punktgenaue Solarprognosen.

---

### 4.8 Open-Source Frameworks (mlforecast, Darts, sktime, tsai)

| Framework | Fokus | Stärken | Schwächen | Lizenz |
|-----------|-------|---------|-----------|--------|
| **mlforecast (Nixtla)** | ML-basiertes Forecasting | Skalierbar (pandas/polars/spark/dask/ray), Conformal Prediction, sklearn-Syntax | Weniger DL-Modelle | MIT |
| **Darts (Unit8)** | All-in-One Time Series | 500+ Modelle (statistisch bis DL), einheitliche API, Probabilistic Forecasting | Speicherintensiv bei großen Daten | Apache 2.0 |
| **sktime** | Unified Time Series ML | 500+ Modelle, Classification/Regression/Clustering, Forecasting, Transformations | Komplexere API, steilere Lernkurve | BSD-3 |
| **tsai** | Deep Learning für Zeitreihen | State-of-the-Art DL (Transformers, CNNs, RNNs), fastai-basiert, Forecasting/Classification | PyTorch/fastai-Abhängigkeit, weniger klassische ML | Apache 2.0 |
| **NeuralForecast (Nixtla)** | Neural Network Forecasting | NHITS, NBEATS, Transformers, Conformal Prediction | Nur DL-Modelle | MIT |
| **skforecast** | ML-Forecasting mit sklearn | Einfach, scikit-learn-kompatibel, Backtesting | Weniger DL-Support | BSD-3 |

**Implementierungsaufwand:** Niedrig bis Mittel (pip-Installation, umfangreiche Dokumentation). Darts und sktime haben die steilste Lernkurve, mlforecast und skforecast sind am einfachsten einzusetzen.

**Empfehlung:**
- **Einstieg (einfach):** skforecast + LightGBM/XGBoost (Quantile Regression)
- **Mittel (Ensemble + Unsicherheit):** mlforecast + Conformal Prediction
- **Fortgeschritten (DL + Transfer Learning):** Darts oder NeuralForecast + PyTorch
- **State-of-the-Art (DL-Architekturen):** tsai mit Transformers (TSTPlus, InceptionTime)

---

## 5. Kostenlose Datenquellen und Feature Engineering

### 5.1 Kostenlose Wetter-APIs

| API | Kosten | Limits | Solar-Daten | Empfehlung |
|-----|--------|--------|-------------|------------|
| **Open-Meteo** | 0 € (non-commercial) | 10.000 Calls/Tag | GHI, DNI, DHI, GTI, Clear-Sky | ★★★★★ |
| **OpenWeatherMap (Free)** | 0 € | 1.000 Calls/Tag | Keine Solarstrahlung (nur Wetter) | ★★☆☆☆ |
| **WeatherAPI (Free)** | 0 € | 100.000 Calls/Monat | UV-Index, Strahlung (eingeschränkt) | ★★★☆☆ |
| **DWD MOSMIX** | 0 € (Open Data) | Keine | Strahlung (rad1h, rad24h) | ★★★★☆ (nur DE) |
| **NOAA/NWS** | 0 € | Keine | GHI über NWP | ★★★☆☆ (nur US) |

### 5.2 Strahlungsdaten

| Quelle | Zeitraum | Auflösung | Kosten | Qualität |
|--------|----------|-----------|--------|----------|
| **ERA5 (ECMWF)** | 1940–heute | 0,1°–0,25° (~11–28 km), stündlich | Kostenlos (Registrierung) | Hoch (Reanalysis) |
| **CAMS (Copernicus)** | 2004–heute | 3–5 km, 15-min | Kostenlos (Registrierung) | Sehr hoch (Satellit) |
| **DWD Strahlung** | Ab 2000 | Stationsbasiert, 10-min | Kostenlos | Sehr hoch (Bodenmessung) |
| **Open-Meteo Solar** | Ab 1940 (ERA5) / 2021 (Forecast) | 1–11 km, stündlich | Kostenlos | Mittel-Hoch |

### 5.3 Satellitenbasierte Strahlung

| Satellit | Abdeckung | Auflösung | Zugang |
|----------|-----------|-----------|--------|
| **MSG/SEVIRI** (Meteosat) | Europa, Afrika | ~3 km, 15-min | EUMETSAT, CAMS, Open-Meteo Satellite API |
| **Himawari-9** | Asien, Australien | ~5 km, 10-min | JAXA P-Tree, Open-Meteo Satellite API |
| **GOES-16/17/18** | Nord-/Südamerika | ~2 km, 5–15 min | NOAA, AWS Open Data |

Open-Meteo Satellite Radiation API: Nutzt MSG für Europa/Afrika, Himawari-9 für Asien/Australien. 10-min-Daten, 30 Min. Verzögerung, Archiv ab 2015.

### 5.4 Historische PV-Daten

| Quelle | Typ | Auflösung | Zugang | Einsatz |
|--------|-----|-----------|--------|---------|
| **PVOutput.org** | Community-Plattform | 5-min (Live), 15-min aggregiert | REST API (kostenlos, API-Key) | ML-Training, Benchmarking |
| **Open-PV (NREL)** | US-Installationsdatenbank | Metadaten only | API (kostenlos) | Systemmetadaten, nicht für Prognosen |
| **Enphase/SMA API** | Hersteller-APIs (Free Tier) | Variabel | API | Eigene Anlage |
| **Kaggle Solar Datasets** | Verschiedene PV-Datensätze | Variabel | Download | ML-Training, Experimente |
| **UCI ML Repository** | PV-Daten | Variabel | Download | ML-Training |

### 5.5 Feature Engineering

**Clear-Sky Index (Kt / CSI):**
```
Kt = GHI_gemessen / GHI_clear_sky
```
Berechnung mit pvlib: `location.get_clearsky(times, model='ineichen')`. Features: `clear_sky_index` (0–1,2), `clear_sky_ghi`, `clear_sky_dni`, `clear_sky_dhi`.

**Solar Position (pvlib):**
```python
solpos = location.get_solarposition(times)
# Features: zenith, azimuth, elevation, equation_of_time
# Abgeleitet: sin/cos(azimuth), cos(zenith), air_mass, sunrise/sunset, hour/day (zyklisch)
```

**Temperatur-Features:**
- `temp_air` (Lufttemperatur 2m), `temp_module` (geschätzt via NOCT-Modell), `temp_delta`
- Modultemperatur: `temp_module = temp_air + (noct - 20) / 800 * ghi` (NOCT ≈ 45°C)
- Effekt auf PV: ca. -0,4%/°C über 25°C (Temperaturkoeffizient)

**Bewölkungs-Features:**
- `cloud_cover` (Gesamtbewölkung %), `cloud_cover_low/mid/high`, `clear_sky_index`
- Wolken-Transit: `cloud_cover_change`, `cloud_cover_rolling_mean` (3h, 6h), `cloud_cover_rolling_std`

**Weitere Features:**

| Feature | Beschreibung | Quelle |
|---------|-------------|--------|
| `wind_speed`, `wind_direction` | Wind (zyklisch) | Wetter-API |
| `humidity` | Relative Feuchte | Wetter-API |
| `pressure` | Luftdruck | Wetter-API |
| `aerosol_optical_depth` | Aerosol-Gehalt | CAMS |
| `precipitation` | Niederschlag | Wetter-API |
| `snow_depth` | Schneehöhe | Wetter-API |
| `soiling` | Verschmutzung (geschätzt) | Berechnet (Tage seit Regen) |

**Lag-Features und Rolling Statistics:**
```python
df['ghi_lag_1h'] = df['ghi'].shift(1)
df['ghi_lag_24h'] = df['ghi'].shift(24)
df['ghi_rolling_mean_3h'] = df['ghi'].rolling(3).mean()
df['ghi_rolling_std_6h'] = df['ghi'].rolling(6).std()
df['ghi_rolling_max_24h'] = df['ghi'].rolling(24).max()
```

### 5.6 Datenqualität und Missing Data Handling

**Typische Probleme:** Fehlende Werte (1–5%), Ausreißer (0,1–1%), Zeitstempel-Lücken, Zeitzonen-Fehler, negative Strahlung, Überstrahlung.

**Imputation-Strategien:**

| Methode | Einsatz |
|---------|---------|
| Lineare Interpolation | Kurze Lücken (<3h) |
| Zeitbasierte Interpolation | Mittlere Lücken (3–6h) |
| Clear-Sky-Fallback | Strahlungslücken |
| KNN-Imputation | Multivariate Daten |
| Forward/Backward Fill | Sehr kurze Lücken |
| Modellbasierte Imputation | Komplexe Muster |

**Best Practice für Solar:**
```python
df['ghi'] = df['ghi'].clip(0, 1400)  # Max ~1400 W/m²
night_mask = (df['solar_elevation'] <= 0)
df.loc[night_mask, 'ghi'] = 0
df['ghi'] = df['ghi'].interpolate(method='time', limit=3)
mask = df['ghi'].isna() & (df['solar_elevation'] > 0)
df.loc[mask, 'ghi'] = df.loc[mask, 'clear_sky_ghi'] * 0.5
```

**Datenvalidierung:** Vollständigkeit (<5% fehlend), Konsistenz (GHI = DNI·cos(θz) + DHI), Plausibilität (0 ≤ GHI ≤ 1400 W/m², 0 ≤ Kt ≤ 1,3), zeitliche Kontinuität (keine Sprünge > 500 W/m² in 15 min), Nacht-Check (GHI ≈ 0 bei Sonnenhöhe < 0°).

**Datenqualität nach Quelle:**

| Quelle | Qualität | Auflösung | Lücken |
|--------|----------|-----------|--------|
| DWD Bodenstation | ★★★★★ | 10 min | Selten |
| CAMS Satellit | ★★★★☆ | 15 min, 3–5 km | Selten |
| ERA5 Reanalysis | ★★★☆☆ | 1 h, 11–28 km | Keine |
| Open-Meteo Forecast | ★★★☆☆ | 1 h, 1–11 km | Selten |
| PVOutput | ★★★☆☆ | 5–15 min | Häufig |
| WeatherAPI | ★★★☆☆ | 1 h, 1 km | Selten |

### 5.6 Datenpipelines und Speicherung

**Empfehlung für Privat:** Cron + Python + SQLite. Vollwertige Orchestratoren (Airflow/Prefect) sind für private Projekte meist überdimensioniert.

**Speicherung:**
- **SQLite:** Empfehlung für Privat, <1M Zeilen, kein Setup, portabel.
- **PostgreSQL:** Exzellent, skalierbar, Multi-Writer.
- **TimescaleDB:** 10–100x schneller für Zeitreihen, Kompression 90%+, Continuous Aggregates.
- **DuckDB/Parquet:** Für ML-Training (schnelle analytische Queries).

**Kostenloser Stack (Minimal):**

| Komponente | Tool | Kosten |
|------------|------|--------|
| Wetter-API | Open-Meteo | 0 € |
| Strahlung | Open-Meteo + pvlib | 0 € |
| PV-Daten | PVOutput.org | 0 € |
| Feature Eng. | pvlib Python | 0 € |
| ML-Modell | scikit-learn / XGBoost | 0 € |
| Datenbank | SQLite | 0 € |
| Pipeline | Cron + Python | 0 € |
| Monitoring | Grafana (optional) | 0 € |

---

## 6. Bewertungstabelle: Modelle und Ansätze

### 6.1 Prognosemodelle und Tools

| # | Modell/Tool | Typ | Genauigkeit | Horizont | Kosten | Lizenz | HA-Integration | Bewertung |
|---|-------------|-----|-------------|----------|--------|--------|----------------|-----------|
| 1 | **Open-Meteo** | NWP-Datenprovider | Modellabhängig | Bis 16 Tage | Kostenlos (10k/Tag) | AGPLv3/CC BY 4.0 | Custom (HACS) | ★★★★☆ |
| 2 | **Forecast.Solar** | Empirisches Modell | Community: moderat | Bis 7 Tage | Free (rate-limited) | Proprietär | Eingebaut | ★★★☆☆ |
| 3 | **pvlib-python** | Framework (Physik) | 10–20% nRMSE | Abhängig von Eingabe | Open Source | BSD-3 | Nein (manuell) | ★★★★☆ |
| 4 | **Solcast (Free)** | Satellit+NWP | Sehr gut (Referenz) | Bis 14 Tage | 10 Calls/Tag | Proprietär | Custom (HACS) | ★★★★☆ |
| 5 | **OpenWeatherMap** | Wetter-API | N/A (keine Solarstrahlung) | 5 Tage | Free (1k/Tag) | Proprietär | Eingebaut | ★★☆☆☆ |
| 6 | **Quartz Solar Forecast** | ML-Modell (GB/XGBoost) | MAE 0,19 kW | 0–48 Stunden | Open Source | MIT | Nein | ★★★☆☆ |
| 7 | **Open-Meteo Solar Forecast** | Strahlung→PV | Modellabhängig | Bis 16 Tage | Open Source | MIT | Custom (HACS) | ★★★★☆ |
| 8 | **Solar-Forecast-ML** | Attention Transformer | Vielversprechend | Variabel | Open Source | Open Source | Custom Integration | ★★★☆☆ |
| 9 | **Solcast Enhanced (Add-on)** | Satellit+NWP + Tuning | Sehr gut | Bis 14 Tage | Free Tier | Proprietär | Add-on | ★★★★☆ |

### 6.2 ML-Modelle und Ansätze

| # | ML-Ansatz | Genauigkeitsverbesserung | Datenbedarf | Aufwand | Bewertung |
|---|-----------|--------------------------|-------------|---------|-----------|
| 1 | **XGBoost/LightGBM/CatBoost** | R² bis 0,998; +15–30% vs. Persistence | 1–2 Jahre stündlich | ★★☆☆☆ | ★★★★★ |
| 2 | **Random Forest** | R² 0,90–0,95; MAE 76 W/m² | 1 Jahr+ stündlich | ★☆☆☆☆ | ★★★★☆ |
| 3 | **LSTM/GRU** | +20–35% vs. Persistence; +8% vs. traditionell | 10k–50k Datenpunkte | ★★★☆☆ | ★★★★☆ |
| 4 | **CNN (Strahlung)** | 20–39% Forecast Skill (intra-hour); 26% (day-ahead) | 6 Monate–6 Jahre Bilder | ★★★★☆ | ★★★☆☆ |
| 5 | **Transformer (Informer/Autoformer)** | -67,64% MSE (D-Informer); R² 0,9917 | Mehrere Jahre multivariat | ★★★★★ | ★★★☆☆ |
| 6 | **Prophet/ARIMA/SARIMA** | MAPE 2,2–24,2%; -59,3% (SARIMA-Kalman) | 1–2 Jahre historisch | ★☆☆☆☆ | ★★★☆☆ |
| 7 | **Hybrid NWP+ML** | +10–25% vs. reine NWP/ML | 1 Jahr+ PV + NWP | ★★★☆☆ | ★★★★★ |
| 8 | **Feature Engineering** | +10–30% Modellgenauigkeit | Abhängig | ★★☆☆☆ | ★★★★★ |
| 9 | **Ensemble (Boosting/Stacking)** | Deutlich besser als Einzelmodelle | Mittlere Datenmengen | ★★☆☆☆ | ★★★★★ |
| 10 | **PINNs** | MSE-Reduktion bis 14,78% | Weniger als reine DL | ★★★★☆ | ★★★☆☆ |
| 11 | **Transfer Learning** | Bis 69% Verbesserung bei Datenknappheit | Vortrainierte Modelle nötig | ★★★☆☆ | ★★★★☆ |
| 12 | **Conformal Prediction / CQR** | Coverage-Garantien (90%) | Calibration-Set nötig | ★★☆☆☆ | ★★★★☆ |
| 13 | **Online Learning** | Adaptive Anpassung | Kontinuierliche Daten | ★★★★☆ | ★★★☆☆ |
| 14 | **Multi-Model Ensemble** | Reduziert Bias einzelner Modelle | Mehrere NWP-Modelle | ★★☆☆☆ | ★★★★☆ |

### 6.3 Datenquellen

| # | Datenquelle | Typ | Auflösung | Kosten | Qualität | Bewertung |
|---|-------------|-----|-----------|--------|----------|-----------|
| 1 | **Open-Meteo** | Wetter + Satellitenstrahlung | Stündlich, 1–11 km | 0 € | ★★★☆☆ | ★★★★★ |
| 2 | **NSRDB (NLR)** | Solarstrahlung (GHI/DNI/DHI) | 30-min, global | 0 € | ★★★★☆ | ★★★★☆ |
| 3 | **PVGIS (EU JRC)** | PV-Ertrag + Wetter | Stündlich, Europa/global | 0 € | ★★★★☆ | ★★★★☆ |
| 4 | **DWD (MOSMIX)** | Wettervorhersage (DE) | Stündlich, ~7 km | 0 € | ★★★★★ | ★★★★☆ |
| 5 | **NOAA GFS/HRRR** | NWP (global/regional) | 3–13 km, 1–6h | 0 € | ★★★★☆ | ★★★★☆ |
| 6 | **ECMWF** | NWP (global) | ~9 km | 0 € (Open Data) | ★★★★★ | ★★★★☆ |
| 7 | **DWD ICON** | NWP (Europa/global) | 2–13 km | 0 € | ★★★★★ | ★★★★☆ |
| 8 | **PVOutput.org** | Community PV-Daten | 5–15 min | 0 € | ★★★☆☆ | ★★★★☆ |
| 9 | **CAMS (Copernicus)** | Satellitenstrahlung | 15-min, 3–5 km | 0 € | ★★★★★ | ★★★★★ |
| 10 | **ERA5 (ECMWF)** | Reanalysis (1940–heute) | 1 h, 11–28 km | 0 € | ★★★★☆ | ★★★★☆ |
| 11 | **Kaggle/UCI Datasets** | PV-Daten | Variabel | 0 € | ★★★☆☆ | ★★★☆☆ |

### 6.4 Open-Source Frameworks

| # | Framework | Fokus | Lizenz | Einfachheit | Bewertung |
|---|-----------|-------|--------|-------------|-----------|
| 1 | **mlforecast (Nixtla)** | ML-Forecasting + Conformal Prediction | MIT | ★★★★☆ | ★★★★★ |
| 2 | **skforecast** | ML-Forecasting mit sklearn | BSD-3 | ★★★★★ | ★★★★☆ |
| 3 | **Darts (Unit8)** | All-in-One Time Series (500+ Modelle) | Apache 2.0 | ★★☆☆☆ | ★★★★☆ |
| 4 | **sktime** | Unified Time Series ML (500+ Modelle) | BSD-3 | ★★☆☆☆ | ★★★★☆ |
| 5 | **tsai** | Deep Learning für Zeitreihen | Apache 2.0 | ★★☆☆☆ | ★★★☆☆ |
| 6 | **NeuralForecast (Nixtla)** | Neural Network Forecasting | MIT | ★★★☆☆ | ★★★★☆ |
| 7 | **pvlib** | PV-Modellierung, Sonnenstand, Clear-Sky | BSD-3 | ★★★★☆ | ★★★★★ |

---

## 7. Empfohlener Stack für private Anwendungen

### 7.1 Minimaler Stack (kostenlos, lokal, wenig Aufwand)

| Schritt | Komponente | Tool | Aufwand |
|---------|-----------|------|---------|
| 1 | Daten | Open-Meteo API (kostenlos, kein Key) | 1 Tag |
| 2 | Physik/Features | pvlib (Solarpos, Clear-Sky, Modultemperatur) | 1 Tag |
| 3 | ML-Modell | LightGBM/XGBoost mit Quantile Regression (skforecast) | 1–2 Tage |
| 4 | Unsicherheit | Conformal Prediction (integriert in mlforecast) | 0,5 Tag |
| 5 | Speicherung | SQLite | 0,5 Tag |
| 6 | Pipeline | Cron + Python | 0,5 Tag |
| 7 | Deployment | FastAPI / Flask → Prognose-API | 1 Tag |

**Gesamtaufwand:** 5–7 Tage | **Genauigkeit:** R² ~0,90–0,95 (stündlich) | **Kosten:** 0 €

### 7.2 Erweiterter Stack (fortgeschritten)

| Schritt | Komponente | Tool |
|---------|-----------|------|
| 1 | Transfer Learning | SolNet (vortrainierte Modelle) für neue Standorte |
| 2 | Hybrid NWP+ML | PINN-iTransformer für physik-konsistente Prognosen |
| 3 | Online Learning | SolarForecast ML (SFML) oder River für adaptive Updates |
| 4 | Multi-Model Ensemble | Open-Meteo Multi-Model (ECMWF+GFS+ICON+HRRR) |
| 5 | Probabilistische Vorhersagen | CQR (Conformalized Quantile Regression) |
| 6 | Speicherung | TimescaleDB (bei >1M Zeilen) |

**Gesamtaufwand:** 2–4 Wochen | **Genauigkeit:** Beste day-ahead-Vorhersagen mit Prediction Intervals

### 7.3 Implementierungsaufwand-Gesamtübersicht

| Ansatz | Aufwand | Nutzen | Empfehlung |
|--------|---------|--------|------------|
| Ensemble (Boosting/Stacking) | ★★☆ | ★★★ | **Sofort einsetzbar** |
| PINNs | ★★★★ | ★★★ | Für Fortgeschrittene |
| NWP+ML Hybrid | ★★★ | ★★★ | **Empfohlen** |
| Multi-Model Ensemble | ★★☆ | ★★☆ | Über Open-Meteo einfach |
| Transfer Learning | ★★★ | ★★★ | Für neue Anlagen |
| Unsicherheitsquantifizierung | ★★☆ | ★★★ | **Empfohlen** |
| Online Learning | ★★★★ | ★★☆ | Für fortgeschrittene Setups |
| Open-Source Frameworks | ★☆☆ | ★★★ | **Grundlage** |

---

## 8. Quellen

### Prognosemodelle und Tools
1. Open-Meteo: https://open-meteo.com | https://github.com/open-meteo/open-meteo
2. Forecast.Solar: https://forecast.solar | https://doc.forecast.solar
3. pvlib-python: https://pvlib-python.readthedocs.io | https://github.com/pvlib/pvlib-python
4. Solcast: https://solcast.com/free-rooftop-solar-forecasting | https://docs.solcast.com.au
5. OpenWeatherMap: https://openweathermap.org | https://openweathermap.org/price
6. Open-Source Quartz Solar Forecast: https://github.com/openclimatefix/open-source-quartz-solar-forecast
7. rany2/open-meteo-solar-forecast: https://github.com/rany2/open-meteo-solar-forecast
8. Solar-Forecast-ML: https://github.com/Zara-Toorox/Solar-Forecast-ML
9. Home Assistant Forecast.Solar: https://www.home-assistant.io/integrations/forecast_solar/
10. HA Open-Meteo Solar Forecast: https://github.com/rany2/ha-open-meteo-solar-forecast
11. Solar Forecast Arbiter: https://forecastarbiter.epri.com
12. HA Community (Solar Forecast Vergleich): https://community.home-assistant.io/t/open-meteo-solar-forecast/733073

### ML-Modelle und Ansätze
13. IntechOpen 2020: "Forecasting of Photovoltaic Solar Power Production Using LSTM" (157 Zit.)
14. MDPI Energies 2023: "Investigating the Power of LSTM-Based Models in Solar Energy Forecasting" (193 Zit.)
15. MDPI Energies 2020: "A Review on Deep Learning Models for Forecasting Time Series Data of Solar Irradiance and Photovoltaic Power"
16. ScienceDirect 2023: "Predictive models development using gradient boosting machine learning algorithms for solar power prediction" (111 Zit.)
17. Mayer et al. 2022: "Comparison of machine learning methods for photovoltaic power forecasting" (629 Zit.)
18. Asiedu et al. 2024: "Machine learning forecasting of solar PV production using NWP" (79 Zit.)
19. ScienceDirect 2022: "Benefits of physical and machine learning hybridization" (207 Zit.)
20. DOI 10.1016/j.solcom.2024.100089: "Application of three Transformer neural networks for short-term photovoltaic power prediction"
21. Energies 2025: "DTCformer: Temporal Convolution-Enhanced Autoformer"
22. Springer 2025: "A comparative study of ARIMA, SARIMA, and LSTM models" (78 Zit.)
23. Nature 2025: "Optimizing solar power forecasting with metaheuristic... FHO-GRU-LSTM"
24. arxiv 2408.00601: "AutoPV: Automatically Design Your Photovoltaic Power Forecasting Model"
25. arxiv 2112.04963: "Model-Agnostic Hybrid NWP and ML for Solar Forecasting"
26. Renewable Energy 2024: "Advanced feature engineering in microgrid PV forecasting"
27. PMC 2025: "Enhancing PV power forecasting through feature selection"
28. Nature 2026: "Accurate Solar Radiation Forecasting Using Spectral Feature Engineering" (FFT)

### Ensemble und hybride Modelle
29. SE2GPA (Springer, 2025): Stacked Ensemble aus vier Boosting-Algorithmen
30. Khan et al. (2022): Deep Ensemble Stacking, ScienceDirect
31. MIPV-NWP-PINN (2025): Copernicus Preprint
32. CNN-LSTM-PINNs (2026): Energies, MDPI
33. SolNet (2025): International Journal of Forecasting
34. Bak et al. (2025): Transfer Learning, IEEE Access
35. Tang et al. (2022): Hybrid DL + Transfer Learning, Renewable & Sustainable Energy Reviews
36. ACI für PV (2026): Nature Scientific Reports
37. CQR für PV (2026): MDPI Sustainability
38. Open Climate Fix Quartz Solar Forecast (GitHub)
39. SolarForecast ML (GitHub: Zara-Toorox)
40. sktime, Darts, mlforecast, tsai (offizielle Dokumentationen)

### Datenquellen und Feature Engineering
41. Open-Meteo: https://open-meteo.com
42. pvlib Python: https://pvlib-python.readthedocs.io
43. PVOutput.org: https://pvoutput.org
44. CAMS Solar: https://atmosphere.copernicus.eu/solar-energy
45. ERA5: https://cds.climate.copernicus.eu
46. DWD Open Data: https://opendata.dwd.de
47. TimescaleDB: https://www.tigerdata.com/timescaledb
48. Prefect: https://www.prefect.io
49. Oil Price API (Feature Engineering): https://www.oilpriceapi.com/blog/feature-engineering-for-solar-energy-data

### GitHub-Repos (Open Source, privat nutzbar)
50. openclimatefix/open-source-quartz-solar-forecast: https://github.com/openclimatefix/open-source-quartz-solar-forecast
51. DVPombo/SOLETE: https://github.com/DVPombo/SOLETE
52. harryman-dev/solar-forecast: https://github.com/harryman-dev/solar-forecast
53. pvlib/pvlib-python: https://github.com/pvlib/pvlib-python
54. williamhobbs/solar-fleet-forecast-probability-tool: https://github.com/williamhobbs/solar-fleet-forecast-probability-tool
55. fmidev/fmi-open-pv-forecast: https://github.com/fmidev/fmi-open-pv-forecast
56. ryukkt62/Suncast (Hugging Face): https://huggingface.co/ryukkt62/Suncast
57. canberkkacan/PV-Panel-Power-Generation-Forecast-with-Random-Forest: https://github.com/canberkkacan/PV-Panel-Power-Generation-Forecast-with-Random-Forest
58. Joris-Dprtr/SolNet: https://github.com/Joris-Dprtr/SolNet
59. gist-ailab/transfer-learning-PV-forecasting: https://github.com/gist-ailab/transfer-learning-PV-forecasting
60. Zara-Toorox/Solar-Forecast-ML: https://github.com/Zara-Toorox/Solar-Forecast-ML

---

*Erstellt: Oktober 2026 | Recherche durchgeführt mit Subagenten | Alle Ressourcen privat kostenlos nutzbar*
