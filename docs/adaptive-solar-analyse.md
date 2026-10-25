# Analyse der Adaptive-Solar-Erweiterung: Ensemble und ML-Learning

Stand: 25.10.2026. Quelle: `custom_components/adaptive_solar/` (Modellkern 0.2.7).

## 1. Kurzfassung

- **Wetter-Ensemble:** Ja. Mehrere Open-Meteo-Modelle können konfiguriert werden; die Baseline ist das arithmetische Mittel der verfügbaren Mitglieder, mit strenger Kohorten-Integrität (kein Auffüllen von Lücken mit 0).
- **ML-Learning:** Konservativ gegatetes Gradient-Boosting auf Residuen (actual − baseline), pro Inverter und Regime (`nwp`/`ghi`), mit chronologischer Train/Validation/Calibration-Aufteilung und empirischen Bounds.
- **Nowcast:** Kurzfristkorrektur (≤3 h) aus realen Leistungs-/GHI-Messungen mit exponentiellem Decay, ohne ML-Kalibrierung der Bounds.

---

## 2. Wettermodelle – Ensemble-Mechanik

### Auswahl und Abruf

- `config_flow.py` bietet 7 Modelle als Multi-Select: `best_match`, `icon_seamless`, `icon_global`, `icon_eu`, `icon_d2`, `ecmwf_ifs025`, `gfs_seamless`. Default: nur `best_match`.
- `weather.py`: alle gewählten Modelle werden parallel abgerufen (`asyncio.gather`), pro Modell eigener Cache (`WEATHER_CACHE_SECONDS = 3600`), Parameter `models=<model>`.
- Modelle haben unterschiedliche Horizonte (`MODEL_DAYS`: `icon_d2` 2 Tage, `icon_eu` 5 Tage, `meteofrance_arome_france` 2 Tage, sonst 16).

### Ensemble-Bildung (engine.py)

Für jedes Ausgabe-Intervall `[start, end)`:

1. **Kohortenbildung:** Nur Modelle mit Original-Quellabdeckung (`p.start <= start and p.end >= end`) werden Mitglieder. Ein Modell mit Lücke trägt nichts bei – keine Interpolation, kein Zero-Fill.
2. **Physik pro Mitglied:** `inverter_power()` für jedes Mitglied.
3. **Baseline:** Arithmetisches Mittel (`fmean`) der Mitglieder-Leistungen.
4. **GHI-Nowcast:** Pro Modell individueller Gain (Haurwitz-normalisiert gegen gemessene Einstrahlung), aber nur angewendet, wenn **alle** Mitglieder der Kohorte Gains haben (`use_ghi`). Gains werden mit Alter exponentiell gedämpft (90-Min-Fenster).

**Eigenschaften:** Keine Modellgewichtung, kein Stacking, keine probabilistische Kombination. Einfacher Mittelwert mit strenger Intervallintegrität.

---

## 3. ML-Learning (ResidualLearner)

### Modell

- `sklearn.ensemble.GradientBoostingRegressor` (Huber-Loss, 100 Bäume, max_depth 3, learning_rate 0.05, min_samples_leaf 8).
- **Pro Inverter und pro Regime** (`nwp` vs. `ghi`) ein eigenes Modell.
- Zielgröße: Residual `actual_w − baseline_w`.
- 13 Features: `baseline_w`, Sonnenhöhe/Azimuth (sin/cos), Tag-des-Jahres (sin/cos), Temperatur, Wind, Bewölkung, `lead_hours`, GHI-Nowcast-Felder.

### Datenbasis

- Archivierte Forecast-Punkte (`_archive_result`) mit Features und Baseline.
- Gemessene Energie-Intervalle aus HA-Recorder (`EnergyIntervalTracker`), nur bei ununterbrochener, nicht abgeregelten Messung.
- `join_training()` verknüpft beides: ≥95% Abdeckung, ≤2.5% Randfehler, ≥30 min, ≥95% Messabdeckung, ganze Messstücke ohne Interpolation.

### Aktivierungsgates

- Mindestens 28 distinct Target-Tage, 240 Target-Stunden.
- Chronologische Blöcke: Train / Validation / Calibration (je min. 4 Holdout-Tage).
- Validation-MAE muss um ≥5% besser als Physik-Baseline sein.
- ≥60% der Validierungstage müssen gewinnen (Daily-Win-Rate).
- Pro Lead-Bin (5 Bins: 0–6 h, 6–24 h, 24–48 h, 48–96 h, 96 h+) eigene Validierung + Kalibration (min. 24 h Train/Val, 4 Tage).
- Kalibrations-Bounds = empirischer absoluter Fehler bei 90% Coverage (nur bei ≥30 h Kalibration und ≥4 Tagen).

### Zwei unabhängige Regime

- `nwp`: markerfreie/legacy-Zeilen.
- `ghi`: Zeilen mit angewandtem GHI-Nowcast.
- Jedes Regime hat eigene Modelle, Gates, Lead-Ranges, Kalibration. Keines aktiviert/kalibriert das andere.

### Vorhersage (predict)

- Nur wenn Lead-Bin unterstützt und Lead im validierten Bereich → Residual addieren, Bounds aus Kalibration.
- Sonst Fallback auf Physik-Baseline (Status `physics_*`).
- Night → 0 W. Invalid features → Physik.

### Nowcast (≤3 h)

- Separat vom ML: beobachtete Leistung vs. instantane Referenz.
- Residual mit exponentiellem Decay (0.75 h Halbwertszeit) auf nächste Intervalle.
- **Keine ML-Kalibrierung** der Bounds (werden auf `None` gesetzt).

### Persistenz

- Archive/Intervalle im HA-Store (`history_v2`), Fingerprints für Physik- und Feature-Änderungen.
- Bei inkompatiblen Features wird der Lerner verworfen, Messdaten bleiben.
- Refit bei jeder Coordinator-Aktualisierung (alle 5 min), wenn History-Revision oder Tag sich ändert.

---

## 4. Optimierungsmöglichkeiten

### A. Wetter-Ensemble (größter Hebel, geringes Risiko)

| Hebel | Was | Nutzen | Risiko |
|---|---|---|---|
| Modell-Gewichtung statt Mittelwert | Gewichte aus Validation-MAE oder historischem Skill | Bessere Baseline bei systematischen Modellunterschieden | Overfitting auf Validierungsperiode |
| Ensemble-Spread als Unsicherheit | Inter-Modell-Streuung zusätzlich zu empirischen Bounds | Realistischere Intervalle (P10/P90) | NWP-Modelle oft unterdispersiv |
| Automatische Modellauswahl | Beste N Modelle pro Standort/Zeitraum | Weniger manuelle Konfiguration | Unterschiedliche Horizonte (icon_d2 = 2 Tage) |
| Kurzfrist-Modell bevorzugen | icon_d2 für lead < 6 h höher gewichten | Höhere Auflösung dort, wo sie zählt | Kohorten-Integrität beibehalten |

**Wichtig – Kohorten-Gates begrenzen den Nowcast (unterschätzter Hebel):**

Die Alles-oder-nichts-Regel ist strenger als die Ensemble-Bildung selbst:

- Stundenpfad (`engine.py:310`): `use_ghi = all(model in ghi_gains ...)` – fehlt **einem** Mitglied der GHI-Gain, wird die Einstrahlungskorrektur für das ganze Intervall verworfen (`ignored:incomplete_reference_cohort`).
- Leistungs-Nowcast (`engine.py:96`, `:101-103`): `_instantaneous_reference` gibt `None` zurück, sobald **ein** Modell keine Originalabdeckung am Messzeitpunkt hat.
- Konsequenz: Mit 1 Modell (Default `best_match`) greift der Nowcast fast immer, mit 4–7 Modellen deutlich seltener. Mehr Modelle verbessern also die Baseline und **verschlechtern** gleichzeitig die Kurzfristkorrektur.
- Gegenmittel: Quorum statt Alles-oder-nichts (z. B. ≥ 2 Mitglieder oder ≥ 60 % der Kohorte), Gewichte unter den verfügbaren Mitgliedern renormalisieren, und die Zahl der beitragenden Mitglieder als Zeilenmetadatum mitschreiben, damit der Lerner darauf konditionieren kann.

### B. ML-Learning (größtes Potenzial, höchster Aufwand)

1. **Lag-Features** – Historische Residuen als Feature (systematische Biases schneller erfassen). Risiko: Autokorrelation.
2. **Clearness-Index-Feature** – `ghi/clear_sky_ghi` als Feature für Wetterregime-Wechsel.
3. **Hyperparameter-Tuning** – Aktuell fest (`n_estimators=100, max_depth=3`). Kleine Grid-Search mit chronologischer Validation möglich, aber flaches Setup ist absichtlich (Anti-Overfitting).
4. **Quantile-Regression statt empirische Bounds** – Direkte P10/P90-Schätzung, asymmetrische Intervalle. Mehr Datenbedarf.
5. **Separate Modelle pro Lead-Bin** – Spezialisierter, aber Datenfragmentierung. Sinnvoll erst bei > 60 Tagen.
6. **Regime-Granularität erhöhen** – z. B. „high-ghi-nowcast" vs. „low-ghi-nowcast".
7. **Aktivierungs-Schwellen senken (vorsichtig)** – „Light"-Aktivierung (14 Tage, ohne Bounds) für Nutzer mit wenig Historie.

### C. Nowcast (hoher Impact, wenig Datenbedarf)

- Mehrere Observations statt nur der neuesten (gewichteter Mittelwert über 15 min).
- Bewölkung/Temperatur-Trend als zusätzliche Korrektur.
- Adaptiver Decay (0.75 h fest) basierend auf Messvarianz.
- GHI-Nowcast-Gain glätten (5-min-Mittelung gegen Wolkenlücken-Spitzen).

### D. Datenqualität & Archivierung

- Mehr Repräsentanten pro Bin (aktuell 1–3 Origins).
- Anker-Persistenz mit Plausibilitätscheck (Neustart-Robustheit).
- Zweite, lockerere Messabdeckungs-Stufe (≥80% für Low-Confidence-Samples).

### E. Performance / HA-Integration

- **Refit-Throttle** – `join_training` läuft alle 5 min über bis zu 30 000 Zeilen; die Fit-Signatur enthält `_history_revision`, die bei jedem Energieintervall hochgezählt wird, weshalb faktisch fast jeder Zyklus neu fittet. Größter Performance-Gewinn bei einfachster Umsetzung: Mindestabstand (z. B. 60 min) oder N neue abgeschlossene Zielstunden.
- Feature-Cache für `_vector()` und `ghi_feature_values()`.
- Archiv-Kompression/Aggregation älterer Zeilen.

### Was man **nicht** tun sollte

- Neural Networks / Deep Learning (zu wenig Daten, kein GPU, Pi-Hardware).
- Modellgewichtung ohne Out-of-Sample-Validierung.
- Gates lockern ohne Messung (5%-Verbesserung, 60%-Win-Rate sind bewusst).
- Nowcast-Bounds als kalibriert präsentieren (Code setzt sie korrekt auf `None`).
- Mehr Modelle = besser (erhöht Kohorten-Lücken-Risiko).

---

## 5. Priorisierte Empfehlung (Top 3)

1. **Refit-Throttle** (E) – Einfachster, sicherster Gewinn, keine Prognose-Änderung.
2. **Modell-Gewichtung + Spread als Unsicherheit** (A) – Messbarer Prognosegewinn, validierbar über bestehende Holdout-Struktur.
3. **Lag-Features** (B.1) – Potenziell großer Gewinn für systematische Biases, aber sorgfältig gegen Overfitting prüfen.

Alles andere erst nach Implementierung und Evaluation dieser drei Hebel anhand von Holdout-MAE und Daily-Win-Rate. Das bestehende Framework (`_fit_regime`, Validation-Gates) bietet dafür bereits eine gute Messbasis.
