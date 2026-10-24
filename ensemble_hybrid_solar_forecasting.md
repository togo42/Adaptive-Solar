# Ensemble-Methoden und hybride Modelle für Solarprognosen
## Strukturierte Zusammenfassung (privat kostenlos nutzbar)

**Stand:** Oktober 2026 | **Quellen:** Wissenschaftliche Literatur, Open-Source-Projekte, Community-Tools

---

## 1. Ensemble-Methoden (Bagging, Boosting, Stacking) für Solar

### Beschreibung
Ensemble-Methoden kombinieren mehrere Modelle, um die Vorhersagegenauigkeit zu verbessern. Drei Hauptansätze:

- **Bagging (Bootstrap Aggregating):** Mehrere Modelle werden auf verschiedenen Bootstrap-Stichproben der Daten trainiert; Vorhersagen werden gemittelt. Reduziert Varianz (z. B. Random Forest).
- **Boosting:** Modelle werden sequentiell trainiert, wobei jedes Modell die Fehler des vorherigen korrigiert. Reduziert Bias (z. B. XGBoost, LightGBM, CatBoost).
- **Stacking:** Mehrere Modelle laufen parallel; ein Meta-Learner kombiniert ihre Vorhersagen zu einer finalen Prognose.

### Vorteile / Nachteile
| Aspekt | Vorteile | Nachteile |
|---|---|---|
| Genauigkeit | Deutlich besser als einzelne Modelle; CatBoost/LightGBM outperformen traditionelle Methoden | Höherer Rechenaufwand beim Training |
| Robustheit | Robust gegen Overfitting (Bagging); hohe Stabilität | Komplexere Hyperparameter-Abstimmung |
| Interpretierbarkeit | Feature Importance verfügbar (Boosting) | Black-Box bei Stacking |
| Datenbedarf | Funktioniert gut mit mittleren Datenmengen | Boosting empfindlich gegenüber Rauschen |

### Implementierungsaufwand
**Mittel.** Standard-ML-Bibliotheken (scikit-learn, XGBoost, LightGBM, CatBoost) bieten Out-of-the-Box-Implementierungen. Ein Stacking-Ensemble lässt sich in wenigen Zeilen mit `sklearn.ensemble.StackingRegressor` aufbauen. Daten-Preprocessing und Feature Engineering sind der Hauptaufwand.

### Open-Source Tools
- **scikit-learn** (`RandomForestRegressor`, `GradientBoostingRegressor`, `StackingRegressor`, `VotingRegressor`)
- **XGBoost**, **LightGBM**, **CatBoost** (Boosting-Bibliotheken, kostenlos)
- **skforecast** – ML-basiertes Forecasting mit scikit-learn-kompatiblen Modellen
- **mlforecast (Nixtla)** – skalierbares ML-Forecasting mit Conformal Prediction

### Relevante Forschung
- SE2GPA (Springer, 2025): Stacked Ensemble aus vier Boosting-Algorithmen für Solarprognose
- Khan et al. (2022): Deep Ensemble Stacking für PV-Prognose an verschiedenen Standorten
- Nature Scientific Reports (2026): CatBoost und LightGBM outperformen traditionelle Methoden bei 1–24h-Horizonten

---

## 2. Physikalisch-informierte neuronale Netze (PINNs) für PV

### Beschreibung
PINNs betten physikalische Gesetze (PDEs/ODEs, z. B. Energiebilanz-Gleichungen von PV-Modulen) direkt in die Loss-Funktion des neuronalen Netzes ein. Das Netz lernt nicht nur aus Daten, sondern auch aus physikalischen Constraints (z. B. Temperatur-ODE des Moduls, Strahlungs-Umwandlungsphysik).

### Vorteile / Nachteile
| Aspekt | Vorteile | Nachteile |
|---|---|---|
| Physik-Konsistenz | Vorhersagen respektieren physikalische Gesetze; bessere Extrapolation | Komplexe Implementierung der physikalischen Constraints |
| Datenbedarf | Weniger Trainingsdaten nötig als reine DL-Modelle | Physikalische Gleichungen müssen bekannt und korrekt formuliert sein |
| Generalisierung | Bessere Generalisierung auf unbekannte Bedingungen | Training kann instabil sein (Multi-Objektiv-Optimierung) |
| Genauigkeit | MSE-Reduktion bis zu 14,78% (Cong et al.) | Höherer Rechenaufwand pro Training |

### Implementierungsaufwand
**Hoch.** Erfordert Kenntnisse in Physik (PV-Modellierung) und Deep Learning (PyTorch/TensorFlow). Physikalische Gleichungen müssen als Loss-Terme implementiert werden. Frameworks wie `DeepXDE` oder `NVIDIA Modulus` vereinfachen dies, aber Anpassung an PV-Domäne ist nötig.

### Open-Source Tools
- **DeepXDE** – generisches PINN-Framework (TensorFlow/PyTorch-Backend)
- **NVIDIA Modulus (PhysicsNeMo)** – NVIDIA's PINN-Framework
- **PyTorch** / **TensorFlow** – Basis für eigene PINN-Implementierungen
- **pvlib** – PV-Physik-Modellierung (kann zur Constraint-Formulierung genutzt werden)

### Relevante Forschung
- MIPV-NWP-PINN (Copernicus, 2025): Multi-Scale-Framework kombiniert WRF-NWP, GHI-Bias-Korrektur (QM-TPA-LSTM) und PINN-iTransformer
- CNN-LSTM-PINNs (Energies, 2026): Hybrides Framework mit räumlichen (CNN) und zeitlichen (LSTM) Abhängigkeiten + physikalische Constraints
- Kazmi et al. (IEEE, 2025): PINN-basierte PV-Prognose mit physikalischen Prinzipien
- PKINN (ScienceDirect, 2026): Photovoltaic Knowledge-Informed Neural Network

---

## 3. Kombination aus NWP und ML

### Beschreibung
Numerical Weather Prediction (NWP) liefert meteorologische Vorhersagen (Strahlung, Temperatur, Wind, Bewölkung). ML-Modelle nutzen diese als Input-Features und korrigieren systematische Fehler (Bias) der NWP-Modelle. Typische Ansätze:

- **Post-Processing:** ML lernt, NWP-Fehler zu korrigieren (z. B. Quantile Mapping + LSTM)
- **Hybrid:** NWP-Outputs als Features in ML-Modellen (XGBoost, LSTM)
- **Spektral-Nudging (ECMWF):** Kombination von ML-großskaligen Vorhersagen mit NWP-physikalischen Details

### Vorteile / Nachteile
| Aspekt | Vorteile | Nachteile |
|---|---|---|
| Genauigkeit | ML korrigiert systematische NWP-Bias; bis zu 23% MAE-Reduktion (MIPV-NWP-PINN) | Abhängig von NWP-Qualität und Verfügbarkeit |
| Horizont | Deckt 0–14 Tage ab (NWP-Stärke) | NWP-Updates nur alle 6–12 Stunden |
| Datenzugang | Kostenlose NWP-Daten verfügbar (Open-Meteo, ECMWF, NOAA) | Hohe Datenmengen; Verarbeitung aufwändig |
| Implementierung | Moderate Komplexität mit bestehenden Frameworks | NWP-Daten-Handling (GRIB, NetCDF) erfordert Spezialwissen |

### Implementierungsaufwand
**Mittel bis Hoch.** NWP-Daten müssen beschafft, verarbeitet und mit historischen PV-Daten aligniert werden. Open-Meteo bietet eine einfache REST-API. Frameworks wie `pvlib` und `xarray` vereinfachen die Verarbeitung. ML-Modellierung selbst ist standard.

### Open-Source Tools
- **Open-Meteo API** – kostenlose NWP-Daten (Strahlung, Temperatur, Wind, Bewölkung), 15-Min-Auflösung
- **ECMWF Open Data** – IFS-Modell (kostenlos für Nicht-kommerzielle Nutzung)
- **NOAA HRRR/GFS** – US-amerikanische NWP-Modelle
- **pvlib** – PV-Modellierung mit Wetterdaten
- **xarray**, **netCDF4** – NWP-Datenverarbeitung
- **Open Climate Fix (Quartz Solar Forecast)** – Open-Source PV-Forecast mit ECMWF/ICON-Vergleich

### Relevante Forschung
- ArXiv 2112.04963: Model-Agnostic Hybrid NWP+ML für Solarprognose in den Tropen
- ECMWF Hybrid Forecasting (2025): Spektral-Nudging von IFS (NWP) und AIFS (ML)
- Solcast: Ensemble aus NWP-Modellen + DL-Korrektur für 4–48h-Fenster

---

## 4. Multi-Model Ensemble (verschiedene Wettermodelle kombinieren)

### Beschreibung
Kombination von Vorhersagen mehrerer unabhängiger NWP-Modelle (ECMWF IFS, NOAA GFS/HRRR, DWD ICON, MeteoFrance) zu einem probabilistischen Ensemble. Methoden:

- **Simple Ensemble Mean:** Einfaches Mittel aller Modelle
- **Weighted Superensemble:** Gewichtung nach historischer Skill
- **Rank-Histogram Calibration:** Anpassung der Ensemble-Spread an beobachtete Klimatologie
- **Bias-Korrektur:** Jedes Modell wird individuell korrigiert, dann kombiniert

### Vorteile / Nachteile
| Aspekt | Vorteile | Nachteile |
|---|---|---|
| Unsicherheit | Natürliche Unsicherheitsquantifizierung durch Ensemble-Spread | Höhere Datenmenge und Rechenaufwand |
| Genauigkeit | Reduziert Bias einzelner Modelle; robustere Vorhersagen | Komplexe Gewichtungsstrategien nötig |
| Datenzugang | Mehrere kostenlose NWP-Quellen verfügbar | Unterschiedliche Auflösungen/Zeitstempel harmonisieren |
| Betrieb | Ausfall eines Modells kompensierbar | Monitoring und Wartung mehrerer Pipelines |

### Implementierungsaufwand
**Mittel.** Open-Meteo aggregiert bereits mehrere Modelle (ICON, GFS, ECMWF, HRRR). Eigenes Multi-Model-Ensemble erfordert Datensammlung, Harmonisierung und Gewichtung. Frameworks wie `xarray` und `pandas` helfen. Für private Nutzung reicht oft Open-Meteo's Multi-Model-API.

### Open-Source Tools
- **Open-Meteo** – aggregiert ECMWF, GFS, ICON, HRRR, MeteoFrance (kostenlos, REST-API)
- **SolarGIS** – nutzt CMV + 4 NWP-Modelle (HRRR, ICON, IFS, GFS)
- **Open Climate Fix Quartz** – Open-Source mit ECMWF vs. ICON Vergleich
- **pvlib** – für PV-Modellierung aus verschiedenen Wetterinputs

### Relevante Forschung
- Solcast: Ensemble aus mesoskaligen + globalen NWP-Modellen + DL-Korrektur
- Solargis: Kombination aus Cloud Motion Vector und 4 NWP-Modellen
- Wikipedia Ensemble Forecasting: Multi-Model Ensemble reduziert Fehler signifikant

---

## 5. Transfer Learning für PV-Prognose

### Beschreibung
Vortrainierte Modelle (z. B. auf großen PV-Datensätzen oder synthetischen PVGIS-Daten) werden auf neue Standorte mit wenig Daten übertragen. Strategien:

- **Feature Extraction:** Vortrainiertes Modell als Feature-Extractor, nur letzte Schicht neu trainiert
- **Fine-Tuning:** Gesamtes Modell wird mit wenigen lokalen Daten nachtrainiert
- **Domain Adaptation:** Anpassung an unterschiedliche Klimazonen/Technologien
- **Synthetic → Real:** Training auf PVGIS-synthetischen Daten, Fine-Tuning auf realen Messungen

### Vorteile / Nachteile
| Aspekt | Vorteile | Nachteile |
|---|---|---|
| Datenbedarf | Funktioniert mit wenig Daten (neue Anlagen, < 1 Jahr) | Source-Domain muss target-ähnlich sein |
| Trainingszeit | Bis zu 71% schnelleres Training (Tang et al.) | Negative Transfer möglich bei zu unterschiedlichen Domänen |
| Genauigkeit | Bis zu 69% Verbesserung bei Datenknappheit | Vortrainierte Modelle müssen verfügbar sein |
| Generalisierung | Cross-continental Transfer möglich (Bak et al., 2025) | Klima-/Technologie-Unterschiede können schaden |

### Implementierungsaufwand
**Mittel.** PyTorch/TensorFlow bieten einfache Transfer-Learning-APIs. Vortrainierte Modelle (SolNet) sind verfügbar. Hauptaufwand: Daten-Pipeline für Source/Target-Domäne und Fine-Tuning-Strategie.

### Open-Source Tools
- **SolNet** (GitHub: Joris-Dprtr/SolNet) – Open-Source Pre-trained DL-Modelle für globale PV-Prognose (PVGIS + Open-Meteo)
- **PyTorch** / **TensorFlow** – Transfer Learning APIs
- **Hugging Face** – Model Hub für vortrainierte Zeitreihen-Modelle
- **gist-ailab/transfer-learning-PV-forecasting** – Transformer-basiertes Cross-Region Transfer Learning

### Relevante Forschung
- SolNet (International Journal of Forecasting, 2025): Two-Step-Pipeline mit Transfer Learning von PVGIS-synthetischen Daten
- PMC (2022): TL mit Stacked LSTM für PV-Produktionsprognose bei Datenknappheit
- Bak et al. (IEEE Access, 2025): Cross-continental Transfer Learning mit 4,5M Datenpunkten
- Tang et al. (Renewable & Sustainable Energy Reviews, 2022): 69,51% Genauigkeits- und 71,42% Effizienzverbesserung

---

## 6. Unsicherheitsquantifizierung (Quantile Regression, Conformal Prediction)

### Beschreibung
Methoden zur Schätzung von Vorhersageintervallen statt nur Punktvorhersagen:

- **Quantile Regression:** Modell wird trainiert, spezifische Quantile (z. B. 10%, 50%, 90%) der Zielverteilung vorherzusagen. Direkt in das Modell integriert.
- **Conformal Prediction:** Post-Processing-Methode, die kalibrierte Vorhersageintervalle mit mathematischer Garantie (Coverage) liefert.
- **Conformalized Quantile Regression (CQR):** Kombination beider Ansätze – Quantile Regression + Conformal-Kalibrierung für schärfere Intervalle.
- **Adaptive Conformal Inference (ACI):** Adaptive Anpassung der Intervalle an nicht-stationäre Daten (z. B. täglicher Reset).

### Vorteile / Nachteile
| Aspekt | Vorteile | Nachteile |
|---|---|---|
| Garantien | Conformal Prediction bietet Coverage-Garantien (z. B. 90%) | Konservativere Intervalle als reine Quantile-Regression |
| Flexibilität | Quantile Regression in jedes Modell integrierbar | Quantile-Crossing-Problem (Quantile überlappen sich) |
| Schärfe | CQR liefert schärfere Intervalle bei gleicher Coverage | Calibration-Set nötig (Datenreduktion) |
| Adaptivität | ACI passt sich an Verteilungsverschiebungen an | Hyperparameter-Abstimmung der Adaptivität |

### Implementierungsaufwand
**Niedrig bis Mittel.** Viele Frameworks bieten Out-of-the-Box-Unterstützung:
- LightGBM/XGBoost: `objective='quantile'` mit `alpha=0.1/0.5/0.9`
- sktime/mlforecast: Conformal Prediction integriert
- NeuralForecast: `PredictionIntervals`-Klasse

### Open-Source Tools
- **mlforecast (Nixtla)** – Conformal Prediction integriert (`PredictionIntervals`)
- **NeuralForecast (Nixtla)** – Quantile + Conformal Prediction
- **LightGBM/XGBoost/CatBoost** – Quantile Regression via `objective='quantile'`
- **scikit-learn** – `QuantileRegressor`
- **MAPIE** – Conformal Prediction Library (Python)
- **NeuralProphet** – Quantile Regression + Conformal Prediction Module

### Relevante Forschung
- MDPI Sustainability (2026): Multi-Scale Temporal-Spatial Attention + CQR für PV
- Nature Scientific Reports (2026): ACI mit täglichem Miscoverage-Reset für PV
- Nam et al. (ScienceDirect, 2025): Conformal Prediction Techniken für Solarprognose

---

## 7. Online Learning / Adaptive Modelle

### Beschreibung
Modelle, die kontinuierlich mit neuen Daten aktualisiert werden, statt batchweise neu trainiert zu werden. Ansätze:

- **Incremental Learning:** Modell wird mit neuen Daten inkrementell aktualisiert (z. B. `partial_fit` in scikit-learn)
- **Streaming ML:** Modelle verarbeiten Datenströme in Echtzeit (z. B. River, Vowpal Wabbit)
- **Drift Detection:** Erkennung von Konzeptdrift (z. B. saisonale Änderungen, Degradation) und automatische Modell-Anpassung
- **Adaptive Ensembles:** Ensemble-Gewichte werden dynamisch an aktuelle Performance angepasst

### Vorteile / Nachteile
| Aspekt | Vorteile | Nachteile |
|---|---|---|
| Aktualität | Modelle passen sich an aktuelle Bedingungen an (Degradation, saisonale Shifts) | Risiko von Catastrophic Forgetting |
| Datenbedarf | Kein großes Retraining nötig | Online-Daten müssen qualitativ hochwertig sein |
| Betrieb | Automatische Anpassung ohne manuelles Eingreifen | Komplexes Monitoring nötig (Drift Detection) |
| Rechenlast | Geringere Rechenlast als Batch-Retraining | Online-Updates können instabil sein |

### Implementierungsaufwand
**Mittel bis Hoch.** Online-Learning-Frameworks (River) bieten einfache APIs, aber Integration in PV-Pipelines erfordert Daten-Streaming-Infrastruktur. Drift-Detection und Modell-Monitoring sind zusätzlicher Aufwand.

### Open-Source Tools
- **River** – Online ML Library für Streaming-Daten (Python)
- **Vowpal Wabbit** – schnelles Online Learning
- **scikit-learn** – `partial_fit` für inkrementelles Lernen (SGDRegressor, etc.)
- **SolarForecast ML (SFML)** – Home Assistant Integration mit adaptive/self-learning Attention Transformer (lokal, privat)
- **OnlineStats.jl** (Julia) – für Echtzeit-Statistiken

### Relevante Forschung
- ResearchGate (2026): LSTM-basiertes Online Learning für Echtzeit-Solarprognose
- ScienceDirect (2026): Adaptive Dual-Path PV-Forecasting für Echtzeit
- SFML v3.0 (Home Assistant Community, 2026): Adaptive Self-Learning für punktgenaue Solarprognosen

---

## 8. Open-Source Frameworks (mlforecast, Darts, sktime, tsai)

### Übersicht

| Framework | Fokus | Stärken | Schwächen | Lizenz |
|---|---|---|---|---|
| **mlforecast (Nixtla)** | ML-basiertes Forecasting | Skalierbar (pandas/polars/spark/dask/ray), Conformal Prediction, sklearn-Syntax | Weniger DL-Modelle | MIT |
| **Darts (Unit8)** | All-in-One Time Series | 500+ Modelle (statistisch bis DL), einheitliche API, Probabilistic Forecasting | Speicherintensiv bei großen Daten | Apache 2.0 |
| **sktime** | Unified Time Series ML | 500+ Modelle, Classification/Regression/Clustering, Forecasting, Transformations | Komplexere API, steilere Lernkurve | BSD-3 |
| **tsai** | Deep Learning für Zeitreihen | State-of-the-Art DL (Transformers, CNNs, RNNs), fastai-basiert, Forecasting/Classification | PyTorch/fastai-Abhängigkeit, weniger klassische ML | Apache 2.0 |
| **NeuralForecast (Nixtla)** | Neural Network Forecasting | NHITS, NBEATS, Transformers, Conformal Prediction | Nur DL-Modelle | MIT |
| **skforecast** | ML-Forecasting mit sklearn | Einfach, scikit-learn-kompatibel, Backtesting | Weniger DL-Support | BSD-3 |

### Implementierungsaufwand
**Niedrig bis Mittel.** Alle Frameworks bieten pip-Installation und umfangreiche Dokumentation. Darts und sktime haben die steilste Lernkurve, mlforecast und skforecast sind am einfachsten einzusetzen.

### Empfehlung für Solarprognosen
- **Einstieg (einfach):** skforecast + LightGBM/XGBoost (Quantile Regression)
- **Mittel (Ensemble + Unsicherheit):** mlforecast + Conformal Prediction
- **Fortgeschritten (DL + Transfer Learning):** Darts oder NeuralForecast + PyTorch
- **State-of-the-Art (DL-Architekturen):** tsai mit Transformers (TSTPlus, InceptionTime)

---

## Zusammenfassung: Empfohlener Stack für private Solarprognose

### Minimaler Stack (kostenlos, lokal)
1. **Daten:** Open-Meteo API (NWP + historisch) + eigene PV-Messungen
2. **Basis-Modell:** LightGBM/XGBoost mit Quantile Regression (skforecast/mlforecast)
3. **Ensemble:** Stacking (XGBoost + LightGBM + Random Forest) via mlforecast
4. **Unsicherheit:** Conformal Prediction (integriert in mlforecast)
5. **PV-Physik:** pvlib für Clear-Sky-Modellierung und Feature Engineering

### Erweiterter Stack (fortgeschritten)
6. **Transfer Learning:** SolNet (vortrainierte Modelle) für neue Standorte
7. **Hybrid NWP+ML:** PINN-iTransformer für physik-konsistente Prognosen
8. **Online Learning:** SolarForecast ML (SFML) oder River für adaptive Updates
9. **Multi-Model Ensemble:** Open-Meteo Multi-Model (ECMWF+GFS+ICON+HRRR)

### Implementierungsaufwand-Gesamtübersicht

| Ansatz | Aufwand | Nutzen für private Solarprognose | Empfehlung |
|---|---|---|---|
| Ensemble (Boosting/Stacking) | ★★☆ | ★★★ | **Sofort einsetzbar** |
| PINNs | ★★★★ | ★★★ | Für Fortgeschrittene |
| NWP+ML Hybrid | ★★★ | ★★★ | **Empfohlen** |
| Multi-Model Ensemble | ★★☆ | ★★☆ | Über Open-Meteo einfach |
| Transfer Learning | ★★★ | ★★★ | Für neue Anlagen |
| Unsicherheitsquantifizierung | ★★☆ | ★★★ | **Empfohlen** |
| Online Learning | ★★★★ | ★★☆ | Für fortgeschrittene Setups |
| Open-Source Frameworks | ★☆☆ | ★★★ | **Grundlage** |

---

## Quellen (Auswahl)

1. Abdellatif et al. (2022): Stacking Ensemble für PV-Prognose, MDPI Sustainability
2. Khan et al. (2022): Deep Ensemble Stacking, ScienceDirect
3. MIPV-NWP-PINN (2025): Copernicus Preprint
4. CNN-LSTM-PINNs (2026): Energies, MDPI
5. SolNet (2025): International Journal of Forecasting
6. Bak et al. (2025): Transfer Learning, IEEE Access
7. Tang et al. (2022): Hybrid DL + Transfer Learning, Renewable & Sustainable Energy Reviews
8. ACI für PV (2026): Nature Scientific Reports
9. CQR für PV (2026): MDPI Sustainability
10. Open Climate Fix Quartz Solar Forecast (GitHub)
11. SolarForecast ML (GitHub: Zara-Toorox)
12. Open-Meteo Solar Forecast (Home Assistant Community)
13. sktime, Darts, mlforecast, tsai (offizielle Dokumentationen)