# Machine-Learning-Verbesserungen für Solar-Prognosemodelle

## Überblick

Diese Zusammenfassung gibt einen strukturierten Überblick über ML-Modelle und Ansätze, die für Solar-PV-Ertragsprognosen privat kostenlos nutzbar sind. Fokus: Open-Source-Tools, kostenlose Datenquellen und praktische Implementierbarkeit.

---

## 1. LSTM / GRU für PV-Ertragsprognose

### Beschreibung
LSTM (Long Short-Term Memory) und GRU (Gated Recurrent Unit) sind rekurrente neuronale Netze (RNNs), die speziell für Zeitreihen entwickelt wurden. Sie erfassen langfristige Abhängigkeiten in historischen Ertrags- und Wetterdaten durch Gating-Mechanismen (Forget/Input/Output-Gates bei LSTM; Reset/Update-Gates bei GRU).

- **GRU** ist vereinfacht (weniger Parameter), trainiert schneller und liefert oft vergleichbare Ergebnisse wie LSTM.
- **LSTM** ist komplexer, aber genauer bei sehr langen Sequenzen.
- Typische Anwendung: 15-min bis 24-h-Vorhersagen für PV-Leistung.

### Genauigkeitsverbesserung
- **LSTM vs. Persistence**: +20–35 % Verbesserung (nRMSE). In Studien RMSE-Verbesserung von ~8 % gegenüber traditionellen ML-Modellen.
- **GRU**: vergleichbar mit LSTM, oft schneller konvergierend.
- Studie (MDPI 2023, 193 Zitationen): LSTM schlägt MLP und physikalische Modelle; CNN-LSTM-Hybrid noch besser.

### Datenanforderungen
- Historische PV-Leistung (min. 1 Jahr, ideal 2–3 Jahre, 15-min oder stündlich)
- Wetterdaten: Irradianz (GHI/DNI), Temperatur, Bewölkung, Wind, Luftfeuchtigkeit
- Mindestens 10.000–50.000 Datenpunkte für stabiles Training

### Implementierungsaufwand
- **Mittel bis Hoch**: Hyperparameter-Tuning (Sequenzlänge, Schichten, Dropout, Learning-Rate), GPU empfohlen
- Benötigt: Daten-Pipeline, Normalisierung, Sliding-Window-Sequenzen

### Open-Source-Bibliotheken
- TensorFlow / Keras, PyTorch, scikit-learn (Vorverarbeitung)

### GitHub-Repos / Papers
- IntechOpen-Kapitel (2020): "Forecasting of Photovoltaic Solar Power Production Using LSTM" (157 Zitationen)
- MDPI Energies 2023: "Investigating the Power of LSTM-Based Models in Solar Energy Forecasting" (193 Zitationen)
- SOLETE-Plattform (DTU): https://github.com/DVPombo/SOLETE (RF, SVM, CNN, LSTM, CNN-LSTM mit TensorFlow/Keras)

---

## 2. XGBoost / LightGBM / CatBoost für Solar

### Beschreibung
Gradient-Boosting-Tree-Ensembles. XGBoost (extreme Gradient Boosting), LightGBM (Light Gradient Boosting Machine) und CatBoost (Categorical Boosting) sind leistungsstarke Tabular-ML-Modelle, die besonders gut mit strukturierten Wetter- und Zeit-Features umgehen. Sie sind robust gegen nicht-lineare Beziehungen und Interaktionen.

- **LightGBM**: schnell, speichereffizient, gut für große Datensätze
- **XGBoost**: hohe Genauigkeit, oft bester Einzelmodell-Performer
- **CatBoost**: exzellent bei kategorialen Features (z. B. Wetterzustände), wenig Hyperparameter-Tuning nötig

### Genauigkeitsverbesserung
- **XGBoost**: in direktem Vergleich (2024, 12 Zitationen) genauestes Modell, gefolgt von LightGBM; LSTM schlechter
- **LightGBM**: R² bis 0.9984 (MSE 2.41) in Studien; sehr schnell
- **CatBoost vs. LightGBM vs. XGBoost**: vergleichbare Genauigkeit, LightGBM/CatBoost schneller
- Verbesserung gegenüber Random Forest: deutlich (XGBoost bevorzugt über RF)
- Verbesserung gegenüber Baseline (Persistence): typisch 15–30 % nRMSE-Reduktion

### Datenanforderungen
- Tabellarische Features: Zeit (Stunde, Monat, Tag des Jahres), Wetter (Irradianz, Temperatur, Bewölkung, Wind), historische Erträge
- Mindestens 1–2 Jahre stündliche Daten
- Keine Sequenzstruktur nötig (im Gegensatz zu LSTM)

### Implementierungsaufwand
- **Niedrig bis Mittel**: Scikit-learn-ähnliche API, schnelles Training (Minuten), wenig Tuning
- Hyperparameter: max_depth, learning_rate, n_estimators, subsample

### Open-Source-Bibliotheken
- `xgboost`, `lightgbm`, `catboost` (alle pip-installierbar, MIT/Apache-Lizenz)
- scikit-learn (Preprocessing, CV, Metriken)

### GitHub-Repos / Papers
- ScienceDirect 2023: "Predictive models development using gradient boosting machine learning algorithms for solar power prediction" (LightGBM, XGBoost, CatBoost)
- Nature 2026: "A stacked Gradient Boosting–XGBoost ensemble" (Solar PV)
- Nature 2025: "Optimizing solar power forecasting with metaheuristic... FHO-GRU-LSTM"
- Kaggle: "Forecasting Solar Power: XGBoost vs LSTM"
- Suncast (Hugging Face): Random Forest via PyCaret, R² 0.748

---

## 3. Random Forest für PV-Leistung

### Beschreibung
Random Forest (RF) ist ein Ensemble aus vielen Entscheidungsbäumen, die auf Bootstrap-Samples trainiert werden. Jeder Baum nutzt zufällige Feature-Subsets. Sehr robust, wenig Overfitting, eingebaute Feature-Importance.

### Genauigkeitsverbesserung
- R² typisch 0.90–0.95 bei stündlicher PV-Leistung
- Suncast-Modell (Hugging Face, PyCaret AutoML): MAE 76 W/m², RMSE 127 W/m², R² 0.748, MAPE 1.49 %
- PVOD-Datensatz: RF R² 0.952, MAE 0.516 (nach Feature-Selection)
- Gute Baseline, aber oft von Boosting-Modellen übertroffen

### Datenanforderungen
- Tabellarisch, 1 Jahr+ stündliche Daten
- Weniger Daten nötig als Deep Learning (RF robust bei kleineren Datensätzen)

### Implementierungsaufwand
- **Niedrig**: scikit-learn `RandomForestRegressor`, schnelles Training
- Hyperparameter: n_estimators, max_depth, min_samples_split

### Open-Source-Bibliotheken
- scikit-learn (`RandomForestRegressor`), PyCaret (AutoML), joblib

### GitHub-Repos / Papers
- github.com/harryman-dev/solar-forecast (RF, DWD MOSMIX, FHEM/MQTT-Integration)
- github.com/canberkkacan/PV-Panel-Power-Generation-Forecast-with-Random-Forest (R² 0.939)
- github.com/SmallSquare/PVOD_Regression (RF/GBM/MLP-Vergleich)
- Hugging Face: ryukkt62/Suncast (RF, China, Apache 2.0)

---

## 4. CNN für Strahlungsprognose

### Beschreibung
Convolutional Neural Networks (CNNs) extrahieren räumliche Features aus Bildern (Himmelkameras, Satellitenbilder) und sind ideal für Wolkenbewegung und Strahlungsprognose (GHI/DNI). 1D-CNNs werden auch für Zeitreihen-Muster genutzt.

- **SolarNet**: 20-schichtiges CNN, nur Himmelbilder als Input, 8.85 % nRMSE, 25.14 % Forecast Skill Score
- **C-GHI**: CNN + Satellitenbilder, bis 26 % Verbesserung gegenüber Persistence (day-ahead)
- **CNN-LSTM Hybrid**: CNN extrahiert räumliche, LSTM zeitliche Features → beste Performance bei Strahlung

### Genauigkeitsverbesserung
- Intra-hour (10–60 min): 20–39 % Forecast Skill über Persistence
- Day-ahead: bis 26 % Verbesserung
- CNN-LSTM: bestes Modell in MDPI-Review (RMSE 8.19 W/m² bei Ghimire et al.)
- CNN-1D: RMSE 36.24 W/m² bei 10-min-Horizont, +11 % vs. Persistence

### Datenanforderungen
- Bild-Daten: Himmelkamera-Aufnahmen oder Satellitenbilder (GOES, MSG)
- Oder: Zeitreihen rekonstruiert als 2D-Matrizen (spatiotemporal)
- Mindestens 6 Monate bis 6 Jahre Daten für robustes Training

### Implementierungsaufwand
- **Hoch**: GPU erforderlich, Bild-Pipeline, viel Speicher, Hyperparameter-Tuning
- Datenvorverarbeitung (Normalisierung, Cropping, Sequenzbildung)

### Open-Source-Bibliotheken
- TensorFlow/Keras, PyTorch, OpenCV, PIL, scikit-image

### GitHub-Repos / Papers
- MDPI Energies 2020: "A Review on Deep Learning Models for Forecasting Time Series Data of Solar Irradiance and Photovoltaic Power"
- ScienceDirect 2020: "Short-term solar irradiance forecasting based on a hybrid CNN-LSTM model" (34 Standorte, 3 Klimazonen)
- OSTI 2022: "Convolutional neural networks for intra-hour solar forecasting based on sky image sequences"
- SolarNet (UT Dallas): 20-layer CNN, 8.85 % nRMSE

---

## 5. Transformer-basierte Modelle (Informer, Autoformer) für Solar

### Beschreibung
Transformer-Modelle nutzen Self-Attention-Mechanismen und sind besonders gut für lange Zeitreihen (Long Sequence Time-Series Forecasting, LSTF). Für Solar wurden spezielle Varianten entwickelt:

- **Informer**: ProbSparse Self-Attention, reduziert Zeit-/Speicherkomplexität, one-shot Long-Sequence-Prediction
- **Autoformer**: Auto-Korrelation statt Self-Attention, Seriendekomposition (Trend + Saisonalität)
- **DTCformer**: Temporal Convolution + Autoformer + DILATE-Loss, +5–42 % Verbesserung bei 24/48/72-h-Vorhersagen
- **CEEMDAN-Informer**: Signaldekomposition + Informer, -30.88 % Fehler gegenüber reinem Informer

### Genauigkeitsverbesserung
- D-Informer: -67.64 % MSE, -49.58 % MAE, -43.43 % RMSE gegenüber Baselines, R² bis 0.9917 (Winter)
- CEEMDAN-Informer: Fehlerindex -30.88 % vs. single Informer
- Vanilla Transformer schlägt Informer und Autoformer in einer Studie (2024, Hubei, China)
- DTCformer: +5–42 % DILATE-Verbesserung bei 24/48/72-h-Vorhersagen

### Datenanforderungen
- Lange Zeitreihen (mehrere Jahre), multivariate Inputs (Irradianz, Temperatur, Wind, historische Leistung)
- Stündliche oder 15-min-Auflösung

### Implementierungsaufwand
- **Hoch**: komplexe Architekturen, viel GPU-Speicher, Hyperparameter-Tuning
- Bibliotheken: PyTorch, Hugging Face Transformers, spezielle Repos (Informer, Autoformer)

### Open-Source-Bibliotheken
- PyTorch, `transformers` (Hugging Face), Informer-Repo (thuml/Informer2020), Autoformer-Repo

### GitHub-Repos / Papers
- DOI 10.1016/j.solcom.2024.100089: "Application of three Transformer neural networks for short-term photovoltaic power prediction" (vanilla Transformer, Informer, Autoformer)
- Frontiers in Energy Research 2023: "Ultra-short-term PV power prediction based on Informer"
- Energies 2025: "DTCformer: Temporal Convolution-Enhanced Autoformer"
- arxiv 2408.00601: "AutoPV: Automatically Design Your Photovoltaic Power Forecasting Model"

---

## 6. Zeitreihen-Modelle (Prophet, ARIMA, SARIMA) für PV

### Beschreibung
Klassische statistische Zeitreihen-Modelle:

- **ARIMA** (AutoRegressive Integrated Moving Average): modelliert Autokorrelation und Trend
- **SARIMA** (Seasonal ARIMA): erweitert ARIMA um saisonale Komponenten (täglich, wöchentlich, jährlich)
- **Prophet** (Facebook/Meta): additiver Trend + Saisonalität + Feiertage, robust bei fehlenden Daten, automatische Changepoint-Erkennung

### Genauigkeitsverbesserung
- SARIMA: gut für saisonale Muster (tägliche/monatliche Solarstrahlung in Seoul)
- Prophet: MAPE 2.2–24.2 % je nach Kontext, gut für Business-Time-Series mit starker Saisonalität
- ARIMA: ARIMA(4,0,1) für US-Solar-Output (12-Monats-Forecast)
- SARIMA-Kalman-Hybrid: -59.3 % Fehler bei Solarstrahlung, -75 % bei Temperatur
- In direktem Vergleich: LSTM oft besser bei nicht-linearen Mustern; Prophet/ARIMA besser bei Interpretierbarkeit und kleinen Daten

### Datenanforderungen
- Univariate oder multivariate Zeitreihen, min. 1–2 Jahre historische Daten
- Prophet robust bei Lücken; ARIMA/SARIMA benötigen regelmäßige Daten

### Implementierungsaufwand
- **Niedrig**: `statsmodels` (ARIMA/SARIMA), `prophet` (pip), einfache API
- Prophet: automatisch, wenig Tuning; ARIMA: ACF/PACF-Analyse nötig

### Open-Source-Bibliotheken
- `statsmodels` (ARIMA, SARIMA, SARIMAX), `prophet` (Meta), `pmdarima` (auto-ARIMA)

### GitHub-Repos / Papers
- github.com/aokdata/Solar_Power_Output_Time_Series (ARIMA + Prophet)
- Preprints 2026: "Comparative Study of Arima, Lstm and Prophet Models for Solar Power Forecasting"
- Springer 2025: "A comparative study of ARIMA, SARIMA, and LSTM models" (78 Zitationen)
- ScienceDirect 2025: "Forecasting energy demand and generation using time series" (SARIMA-Kalman)

---

## 7. Hybride Modelle (NWP + ML)

### Beschreibung
Kombination von Numerical Weather Prediction (NWP) mit Machine Learning. NWP liefert meteorologische Vorhersagen (Irradianz, Temperatur, Bewölkung), ML lernt die nicht-lineare Abbildung auf PV-Leistung. Varianten:

- **NWP + XGBoost/LightGBM**: tabellarisch, schnell, sehr genau
- **NWP + LSTM/GRU**: sequentiell, erfasst zeitliche Dynamik
- **NWP + CNN-LSTM**: spatiotemporal (Wolkenfelder)
- **NWP + Ensemble**: Random Forest + XGBoost Quantile Regression für probabilistische Vorhersagen
- **Model-Agnostic Hybrid**: mehrere NWP-Modelle + ML-Korrektur

### Genauigkeitsverbesserung
- Mayer et al. 2022 (629 Zitationen): 24 ML-Modelle für day-ahead PV-Forecasting auf NWP-Basis verglichen
- Asiedu et al. 2024 (79 Zitationen): Hybrid-Modelle übertreffen Single-Modelle
- NWP+ML typisch 10–25 % besser als reine NWP oder reine ML
- Quantile Regression (RF/XGBoost): probabilistische Vorhersagen mit Prediction Intervals

### Datenanforderungen
- NWP-Daten (kostenlos: ECMWF, DWD ICON, NOAA GFS/HRRR, Open-Meteo)
- Historische PV-Leistung (min. 1 Jahr)
- Standort-spezifische Kalibrierung

### Implementierungsaufwand
- **Mittel bis Hoch**: NWP-Daten-Pipeline, Feature-Engineering, Modell-Training, Ensemble-Management

### Open-Source-Bibliotheken
- pvlib (PV-Modellierung), Herbie (NOAA-Daten), xarray, pandas, scikit-learn, XGBoost/LightGBM

### GitHub-Repos / Papers
- github.com/williamhobbs/solar-fleet-forecast-probability-tool (XGBoost/RF Quantile, HRRR/GEFS, BSD-3)
- arxiv 2112.04963: "Model-Agnostic Hybrid NWP and ML for Solar Forecasting"
- ScienceDirect 2022: "Benefits of physical and machine learning hybridization" (Mayer et al.)
- PMC 2024: "Machine learning forecasting of solar PV production using NWP"

---

## 8. Feature Engineering

### Beschreibung
Die Qualität der Features ist oft wichtiger als das Modell. Wichtige Feature-Kategorien:

**Zeit-Features:**
- Stunde, Monat, Tag des Jahres, Wochentag
- Zykliche Kodierung (sin/cos) für Stunde/Monat
- Sonnenstand (Azimut, Elevation, Zenith) via pvlib

**Wetter-Features:**
- Globale Horizontalstrahlung (GHI), Direktstrahlung (DNI), Diffusstrahlung (DHI)
- Temperatur (Luft, Modul), Windgeschwindigkeit, Luftfeuchtigkeit, Bewölkung
- Historische Irradianz (Lags: 1h, 2h, 24h)

**PV-spezifische Features:**
- Klarheitsindex (Clear Sky Index, CSI)
- Clear-Sky-Strahlung (pvlib)
- Historische Erträge (Lags, Rolling Means)

**Spatiotemporale Features:**
- Umgebungsstandorte (räumliche Interpolation)
- Satellitenbilder (CNN)

### Genauigkeitsverbesserung
- Studien zeigen: Feature-Engineering kann Modellgenauigkeit um 10–30 % verbessern
- Zykliche Zeitkodierung: +5–10 % vs. rohe Stunden
- Clear-Sky-Index: sehr wichtig für Normalisierung
- Feature-Selection (Korrelation, SHAP): reduziert Overfitting, verbessert Generalisierung

### Implementierungsaufwand
- **Mittel**: pvlib für Sonnenstand/Clear-Sky, pandas für Lags/Rolling, scikit-learn für Scaling

### Open-Source-Bibliotheken
- `pvlib`, `pandas`, `numpy`, `scikit-learn`, `shap` (Feature-Importance)

### Papers
- Renewable Energy 2024: "Advanced feature engineering in microgrid PV forecasting"
- PMC 2025: "Enhancing PV power forecasting through feature selection"
- Nature 2026: "Accurate Solar Radiation Forecasting Using Spectral Feature Engineering" (FFT)

---

## 9. Open-Source ML-Bibliotheken

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

## Kostenlose Datenquellen

| Quelle | Typ | Auflösung | Kosten | Zugang |
|--------|-----|-----------|--------|--------|
| **Open-Meteo** | Wetter + Satellitenstrahlung | stündlich, global | kostenlos (non-commercial) | REST API, kein Key |
| **NSRDB (NLR)** | Solarstrahlung (GHI/DNI/DHI) | 30-min, global | kostenlos | API / Download |
| **PVGIS (EU JRC)** | PV-Ertrag + Wetter | stündlich, Europa/global | kostenlos | API / Web |
| **DWD (MOSMIX)** | Wettervorhersage (Deutschland) | stündlich | kostenlos | API / FTP |
| **NOAA GFS/HRRR** | NWP (global/regional) | 3–13 km, 1–6h | kostenlos | Herbie / NOMADS |
| **ECMWF** | NWP (global) | ~9 km | kostenlos (Open Data) | API |
| **DWD ICON** | NWP (Europa/global) | ~2–13 km | kostenlos | Open Data |
| **Kaggle-Datasets** | PV-Ertrag (verschiedene Standorte) | variabel | kostenlos | Download |
| **UCI ML Repository** | PV-Daten | variabel | kostenlos | Download |

---

## Empfohlene GitHub-Repos (Open Source, privat nutzbar)

1. **openclimatefix/open-source-quartz-solar-forecast** — Open-Source PV-Forecast (0–48h), Python, MIT-ähnlich
   https://github.com/openclimatefix/open-source-quartz-solar-forecast

2. **DVPombo/SOLETE** — ML-Forecasting-Plattform (RF, SVM, CNN, LSTM, CNN-LSTM) mit TensorFlow/Keras, MIT
   https://github.com/DVPombo/SOLETE

3. **harryman-dev/solar-forecast** — Random Forest, DWD MOSMIX, FHEM/MQTT, produktiv einsetzbar
   https://github.com/harryman-dev/solar-forecast

4. **pvlib/pvlib-python** — PV-Modellierung, Wetterdaten-Tools, BSD-3
   https://github.com/pvlib/pvlib-python

5. **williamhobbs/solar-fleet-forecast-probability-tool** — XGBoost/RF Quantile Regression, probabilistische Vorhersagen, BSD-3
   https://github.com/williamhobbs/solar-fleet-forecast-probability-tool

6. **fmidev/fmi-open-pv-forecast** — PV-Vorhersage aus Wetterdaten, Python
   https://github.com/fmidev/fmi-open-pv-forecast

7. **ryukkt62/Suncast (Hugging Face)** — Trainiertes RF-Modell, PyCaret, Apache 2.0
   https://huggingface.co/ryukkt62/Suncast

8. **canberkkacan/PV-Panel-Power-Generation-Forecast-with-Random-Forest** — RF, R² 0.939, Unlicense
   https://github.com/canberkkacan/PV-Panel-Power-Generation-Forecast-with-Random-Forest

---

## Empfohlene Architektur für private Nutzung (Kostenlos)

### Szenario A: Einfach & schnell (wenig Daten, wenig Aufwand)
- **Modell**: XGBoost oder LightGBM
- **Daten**: Open-Meteo API (kostenlos) + eigene PV-Historie (1 Jahr)
- **Features**: Zeit (zyklisch), Irradianz, Temperatur, historische Erträge (Lags)
- **Aufwand**: 1–2 Tage
- **Genauigkeit**: R² ~0.90–0.95 (stündlich)

### Szenario B: Mittel (mehr Daten, Deep Learning)
- **Modell**: CNN-LSTM oder GRU
- **Daten**: NSRDB/PVGIS (2–3 Jahre) + eigene PV-Historie
- **Features**: Multivariate Sequenzen (24h-Fenster)
- **Aufwand**: 1–2 Wochen (GPU empfohlen)
- **Genauigkeit**: +10–20 % vs. Szenario A

### Szenario C: Fortgeschritten (probabilistisch, NWP-basiert)
- **Modell**: NWP + XGBoost Quantile Regression (Ensemble)
- **Daten**: DWD ICON / Open-Meteo + PV-Historie
- **Features**: NWP-Irradianz, Temperatur, Bewölkung, PV-Lags
- **Aufwand**: 2–4 Wochen
- **Genauigkeit**: beste day-ahead-Vorhersagen, mit Prediction Intervals

---

## Quellen (Auswahl)

- IntechOpen 2020: "Forecasting of Photovoltaic Solar Power Production Using LSTM" (157 Zit.)
- MDPI Energies 2023: "Investigating the Power of LSTM-Based Models in Solar Energy Forecasting" (193 Zit.)
- MDPI Energies 2020: "A Review on Deep Learning Models for Forecasting Time Series Data of Solar Irradiance and Photovoltaic Power"
- ScienceDirect 2023: "Predictive models development using gradient boosting machine learning algorithms for solar power prediction" (111 Zit.)
- Mayer et al. 2022: "Comparison of machine learning methods for photovoltaic power forecasting" (629 Zit.)
- Asiedu et al. 2024: "Machine learning forecasting of solar PV production using NWP" (79 Zit.)
- ScienceDirect 2022: "Benefits of physical and machine learning hybridization" (207 Zit.)
- DOI 10.1016/j.solcom.2024.100089: "Application of three Transformer neural networks for short-term photovoltaic power prediction"
- Energies 2025: "DTCformer: Temporal Convolution-Enhanced Autoformer"
- Springer 2025: "A comparative study of ARIMA, SARIMA, and LSTM models" (78 Zit.)
- Nature 2025: "Optimizing solar power forecasting with metaheuristic... FHO-GRU-LSTM"
- arxiv 2408.00601: "AutoPV: Automatically Design Your Photovoltaic Power Forecasting Model"