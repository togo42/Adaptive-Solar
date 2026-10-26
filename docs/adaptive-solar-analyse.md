# Analyse der Adaptive-Solar-Erweiterung: Ensemble und ML-Learning

Stand: 26.10.2026. Gegen Codebasis 0.2.11 abgeglichen. Abschnitte 1–3 beschreiben den Code; Abschnitte 4–5 sind mögliche Prüfaufträge, keine belegten Optimierungen oder automatisch beauftragten Modelländerungen. [Vertrag](implementation-contract.md), [Anwenderhandbuch](bedienung.md).

## 1. Kurzfassung

- **Wetter-Ensemble:** Ja. Mehrere Open-Meteo-Modelle können konfiguriert werden; die Baseline ist das arithmetische Mittel der verfügbaren Mitglieder, mit strenger Kohorten-Integrität (kein Auffüllen von Lücken mit 0).
- **ML-Learning:** Konservativ gegatetes Gradient-Boosting auf Residuen (actual − baseline), pro Inverter und Regime (`nwp`/`ghi`), mit chronologischer Train/Validation/Calibration-Aufteilung und empirischen Bounds.
- **Nowcast:** Kurzfristkorrektur (≤3 h) aus realen Leistungs-/GHI-Messungen mit exponentiellem Decay, ohne ML-Kalibrierung der Bounds.

---

## 2. Wettermodelle – Ensemble-Mechanik

### Auswahl und Abruf

- `config_flow.py` bietet 7 Modellvorgaben und erlaubt eigene Kennungen: `best_match`, `icon_seamless`, `icon_global`, `icon_eu`, `icon_d2`, `ecmwf_ifs025`, `gfs_seamless`. Default: nur `best_match`.
- `weather.py`: alle gewählten Modelle werden parallel abgerufen (`asyncio.gather`), pro Modell eigener Cache (`WEATHER_CACHE_SECONDS = 3600`), Parameter `models=<model>`.
- Modelle haben unterschiedliche Horizonte (`MODEL_DAYS`: `icon_d2` 2 Tage, `icon_eu` 5 Tage, `meteofrance_arome_france` 2 Tage, sonst 16).

### Ensemble-Bildung (engine.py)

Für jedes Ausgabe-Intervall `[start, end)`:

1. **Kohortenbildung:** Nur Modelle mit Original-Quellabdeckung (`p.start <= start and p.end >= end`) werden Mitglieder. Ein Modell mit Lücke trägt nichts bei – keine Interpolation, kein Zero-Fill.
2. **Physik pro Mitglied und Stufe:** Nur numerisch gültige Stufen-/Modellzellen bleiben in der jeweiligen Kohorte; ein Fehler einer Stufe verwirft nicht automatisch andere Stufen.
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
- Gemessene Energieintervalle erzeugt `EnergyIntervalTracker` aus kumulativen PV-Zählerberichten über HA-Zustandsereignisse; die Messung muss zusammenhängend und ungedrosselt sein.
- `join_training()` verknüpft beides: mindestens 30 Minuten Zielzeit, mindestens 95 % Messabdeckung und höchstens 2,5 % Lücke an jedem Rand; ganze Messstücke ohne erfundene Randenergie.

### Aktivierungsgates

- Mindestens 28 distinct Target-Tage, 240 Target-Stunden.
- Chronologische Blöcke: Train / Validation / Calibration (je min. 4 Holdout-Tage).
- Validation-MAE muss strikt mehr als 5 % unter der Physik-Baseline liegen; Gleichheit am Schwellwert wird im Code abgelehnt.
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
- Residual mit exponentiellem Decay (0,75 h Zeitkonstante; Halbwertszeit etwa 31,2 min) auf nächste Intervalle.
- **Keine ML-Kalibrierung** der Bounds (werden auf `None` gesetzt).

### Persistenz

- Archive/Intervalle im HA-Store (`history_v2`), Fingerprints für Physik- und Feature-Änderungen.
- Featurevertrag v2 verwirft unverifizierbare alte Forecastfeatures/Modelle. Messintervalle und Tagesbeginn-Snapshots bleiben nur bei passender separat geprüfter physischer Provenienz. Physische Änderungen können auch Messhistorie unbrauchbar machen.
- Optionale Messgültigkeit sperrt Energie-/Powerbeobachtungen; restaurierte numerische Eingangswerte werden verworfen. Morgen-/Abenddämpfung ist seit 0.2.10 ein physikalischer Stringparameter vor dem gemeinsamen Ausgangsclip.
- Refit bei jeder Coordinator-Aktualisierung (alle 5 min), wenn History-Revision oder Tag sich ändert.

---

## 4. Mögliche Prüfaufträge

Die folgende Reihenfolge ist eine Arbeitshypothese. Es gibt keine aktuelle Messung,
die einen dieser Kandidaten bereits als bessere Forecastpolitik belegt.

### A. Wetter-Ensemble und Kohorten

Modellgewichte oder automatische Modellauswahl wären neue Modellpolitiken. Zuerst
je Modell/Stufe/Horizont Abdeckung, Bias und Energie-MAE auf identischen Aufgaben
messen. Auswahl und abschließende Bewertung brauchen getrennte Zeitblöcke.
`best_match` und weitere Arme können sich überlappen; keine Unabhängigkeit annehmen.

Der Code verlangt für GHI vollständige Unterstützung der gültigen Stufenkohorte
und für Power dieselbe Kohorte am Messzeitpunkt. Daraus folgt kein gemessener Satz
„mehr Modelle verschlechtern den Nowcast“. Die Häufigkeit/Wirksamkeit muss aus
Diagnosen bestimmt werden. Ein Quorum würde die Baseline-/Featuresemantik ändern
und ist kein bloßes Lockern eines Darstellungsfilters.

Ensemble-Spread darf zunächst als Modellunterschied untersucht werden. Für
P10/P90-Aussagen sind eigene zeitlich getrennte Kalibrierungs-/Coverageprüfungen nötig.

### B. Lernfeatures und Modellaufteilung

Ein zusätzlicher Clearness-Index oder lokale Residual-Lags sind mögliche Ablationen.
Bei Lags muss die Referenzmessung tatsächlich vor Ausgabe verfügbar gewesen sein.
Der bestehende GHI-Gain ist nicht automatisch ein unabhängiges neues Wetterfeature.
Neue Features benötigen einen neuen Archiv-/Featurevertrag.

Hyperparameter, feinere Regime oder separate Leadmodelle nur bei ausreichender
Datenunterstützung prüfen. Weder ein pauschaler 60-Tage-Schwellwert noch ein
voreiliger 14-Tage-„Light“-Modus ist als Verbesserung belegt. Qualitäts-/Aktivierungsgates
werden durch diese Dokumentation nicht verändert.

### C. Nowcast

Beobachtungsglättung, Trends und adaptives Abklingen könnten Rauschen oder Verzögerung
verändern. Ein Vergleich braucht identische echte Berichtzeiten, Quellenkohorten,
GHI-/Power-Abgrenzung und die aktuelle Baseline als Referenz. Gemittelte Beobachtungen
dürfen nicht als neue momentane Messungen ausgegeben werden.

### D. Datenqualität und Archivierung

Mehr Origins dürfen keine mehrfachen Iststunden erzeugen. Messabdeckung lockern,
Lücken auffüllen oder einen Energieanker über Neustarts erhalten würde bisherige
Sicherheitsannahmen ändern. Solche Änderungen sind keine Standardoptimierung und
brauchen eigene Quellen-/Chronologienachweise. Ein zusätzlicher Qualitätsstatus
macht ein ungeeignetes Label nicht zu einer validierten Messung.

### E. Refit und Ressourcen

Der Coordinator prüft alle fünf Minuten die Fit-Signatur aus Historienrevision und
lokalem Tag. Neue Messintervalle verändern die Revision. Erst CPU-/Laufzeit-/Speicher-
Messungen können zeigen, ob Rekonstruktion den Betrieb relevant belastet.

Ein Refit-Throttle oder Featurecache könnte Aufwand sparen, kann aber Modellaktualität
und Reaktionen nach Qualitätswechseln beeinflussen. Deshalb Ergebnisalter und
Forecastparität bzw. bewusst erlaubte Abweichungen mitprüfen. Ein sicherer Gewinn
oder unveränderte Prognosen werden nicht vorab behauptet.

## 5. Priorität und messbare Abnahme

1. **Bestehende Quellen und Baseline qualifizieren:** Diagnosen, echte Zählerberichte,
   Abdeckung und prospektive Archive prüfen. Fehlende produktive ML-/Gütebelege
   bleiben vor jeder Optimierung sichtbar.
2. **Refitkosten messen:** Nur bei relevantem Aufwand einen Kandidaten mit vorher
   festgelegtem Aktualitäts-/Qualitätsbudget gegen die unveränderte Rekonstruktion prüfen.
3. **Einzelne Modell-/Featurekandidaten ablatieren:** Identische historische Inputs,
   unveränderte Messgates, getrennte Auswahl-/Prüftage und Auswertung je Stufe/Horizont.

Der externe Annahmenachweis folgt dem [Validierungsplan](validierung.md): mindestens
30 vollständige gepaarte Zieltage je Stratum gegen beide Referenzen, nicht bloß ein
intern bestandener Holdout. Test-/Reviewbestehen oder kleinere Refitzeiten beweisen
keinen Forecastvorsprung. Für diese Dokumentationskorrektur wurde kein neuer
Modellkandidat implementiert und keine produktive Einstellung geändert.
