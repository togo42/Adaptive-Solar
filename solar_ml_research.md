# Machine-Learning-Verbesserungen für Solar-Prognosemodelle

Stand: 26.10.2026. Dieser Methodenvergleich unterscheidet verfügbare Verfahren von
der [konkreten Adaptive-Solar-Implementierung](docs/implementation-contract.md).
Nicht eindeutig belegte Verbesserungsprozente, Zitationszahlen und pauschale
Ranglisten wurden entfernt. Die verlinkten Primärdokumentationen belegen die
Methoden; sie ersetzen keinen PV-Test mit festem Datensatz und Forecastcutoff.

## 1. LSTM / GRU für PV-Ertragsprognose

Rekurrente Netze verarbeiten Sequenzen. Die offizielle Dokumentation zu
[Keras LSTM](https://keras.io/api/layers/recurrent_layers/lstm/) und
[GRU](https://keras.io/api/layers/recurrent_layers/gru/) definiert Eingaben und
Zustandsführung. PV-Kandidaten könnten vergangene Leistung und Wettersequenzen
verwenden, benötigen dafür aber lücken- und verfügbarkeitsbewusste Trainingsdaten.

Eine feste Mindestzahl von Jahren oder Punkten ist keine allgemeine Gütezusage.
Fensterlänge und Datenmenge müssen gegen zeitlich spätere Prüfblöcke untersucht
werden. Adaptive Solar verwendet keine LSTM/GRU und benötigt kein GPU-Training.

## 2. XGBoost / LightGBM / CatBoost für Solar

Dies sind alternative Boostingbibliotheken für tabellarische Merkmale:
[XGBoost](https://xgboost.readthedocs.io/), [LightGBM](https://lightgbm.readthedocs.io/)
und [CatBoost](https://catboost.ai/docs/). Keine dieser Bibliotheken ist im Projekt
als Lernmodell implementiert. Der lokale Regressor stammt aus scikit-learn.

Ein Wechsel müsste bei gleicher Baseline, denselben verfügbaren Features und
Labels sowie demselben Prüfzeitraum untersucht werden. Eine neue Bibliothek kann
andere Binärabhängigkeiten und HAOS-Anforderungen mitbringen. Laufzeit, Speicher,
Fehler und Bias sind getrennte Auswahlkriterien; eine universelle Rangfolge fehlt.

## 3. Random Forest für PV-Leistung

[RandomForestRegressor](https://scikit-learn.org/stable/modules/generated/sklearn.ensemble.RandomForestRegressor.html)
ist eine mögliche nichtlineare tabellarische Referenz. Einzelbäume arbeiten mit
verschiedenen Stichproben/Merkmalsauswahlen. Eine Zeitreihenbewertung braucht
chronologische Auswertung auch dann, wenn der Lerner intern zufällige Stichproben zieht.

PV-Leistungsfehler in W sind nicht mit Strahlungsfehlern in W/m² austauschbar.
R² ohne Nachtfilter, Standort, Horizont und Basislinie erlaubt keine Prognoserangliste.
Es wird hier deshalb kein typischer R²- oder MAPE-Wert angegeben.

## 4. CNN für Strahlungsprognose

CNNs können räumliche Muster etwa in Himmels- oder Satellitenbildern auswerten;
[Keras Conv2D](https://keras.io/api/layers/convolution_layers/convolution2d/)
beschreibt die Modellkomponente. Für einen Forecast müssen Bildaufnahme,
Verarbeitungsverzug und Zielhorizont vorab definiert werden. Ein aktuelles Satellitenbild
ist keine Information, die für einen historischen Forecast rückwirkend bekannt war.

Bildzugang, Lizenz, Registrierung und Rechenaufwand sind zusätzlich zum ML-Modell
zu prüfen. Adaptive Solar ruft weder Himmelsbilder ab noch verarbeitet es Satellitenbilder.

## 5. Transformer-basierte Modelle (Informer, Autoformer) für Solar

Aufmerksamkeit kann lange Sequenzen modellieren. Die offizielle
[PyTorch-Transformer-Dokumentation](https://docs.pytorch.org/docs/stable/generated/torch.nn.Transformer.html)
belegt den generischen Baustein, keinen Solarbenchmark oder Vorsprung einer
konkreten Architektur. Spezialisierte Varianten sind jeweils anhand ihrer eigenen
reproduzierbaren Quellen und Datenbedingungen zu prüfen.

Scaler, Featureselektion und Hyperparameter dürfen nicht an späteren Testtagen
angepasst werden. Größere Architekturkomplexität rechtfertigt weder eine gelockerte
Messqualifikation noch den Vergleich gegen eine schwächer konfigurierte Referenz.

## 6. Zeitreihen-Modelle (Prophet, ARIMA, SARIMA) für PV

[SARIMAX in statsmodels](https://www.statsmodels.org/stable/generated/statsmodels.tsa.statespace.sarimax.SARIMAX.html)
unterstützt saisonale autoregressive Modelle mit optionalen externen Regressoren.
[Prophet](https://facebook.github.io/prophet/docs/quick_start.html) beschreibt ein
anderes Zeitreihenmodell mit Trend-/Saisonkomponenten. Beide sind mögliche
Forschungskandidaten, keine eingebauten Adaptive-Solar-Modelle.

Tagesgang und Saison allein sagen wechselnde Bewölkung nicht voraus. Fehlende
Intervalle, physische Grenzen und die tatsächliche Zukunftsverfügbarkeit externer
Wetterfeatures müssen unabhängig von der Bibliothek berücksichtigt werden.

## 7. Hybride Modelle (NWP + ML)

Adaptive Solar rechnet zunächst PV-Physik und lernt dann das Residuum
`actual_w - baseline_w` mit
[GradientBoostingRegressor](https://scikit-learn.org/stable/modules/generated/sklearn.ensemble.GradientBoostingRegressor.html).
Der [lokale Code](custom_components/adaptive_solar/core/learning.py) verwendet
Huber-Loss, 100 Bäume, Tiefe 3, Lernrate 0,05 und mindestens acht Zeilen pro Blatt.
NWP und angewandte GHI-Korrektur haben getrennte Lernregime.

Die [internen Gates](docs/implementation-contract.md) betreffen mindestens 28 Zieltage,
240 Stunden eindeutiger Messdauer, chronologische Holdouts und belegte Leadbereiche.
Das sind Implementierungsparameter, keine Literaturwerte oder externe Gütezusage.
Eine physikalische Baseline bleibt bei fehlender qualifizierter Historie aktiv.

## 8. Feature Engineering

Zeitlich zyklische Kodierung, Sonnengeometrie, Wetter und verfügbare Residualhistorie
sind mögliche Merkmale. [pvlib-Sonnenposition](https://pvlib-python.readthedocs.io/en/stable/reference/solarposition.html)
liefert geometrische Größen. Ein Clear-Sky-Index normalisiert Strahlung gegen eine
Klarhimmelreferenz; er braucht ausreichende Sonnenhöhe und konsistente Zeitunterstützung.

| Feature | Verfügbarkeit und Risiko | Projektstand |
| --- | --- | --- |
| Sonnenhöhe/Azimut, Jahressaison | Zum Zielzeitpunkt deterministisch berechenbar | Enthalten |
| NWP-Temperatur/Wind/Bewölkung | Nur aus dem tatsächlich empfangenen Wetterstand | Enthalten |
| GHI-Gain/Regime/Beobachtungsalter | Nur mit gültiger ursprünglicher Beobachtungszeit | Enthalten |
| Lokale Residual-Lags | Zielmessung muss schon vor Ausgabe verfügbar sein | Kein zusätzlicher Lagvektor implementiert |
| Nachträgliche ERA5-/Istwerte | Nicht als damalige Zukunftseingaben ausgeben | Für prospektive Features ungeeignet |

Featureverbesserung ist durch Ablation zu messen. Pauschale Aussagen wie
„zyklische Zeitkodierung bringt 5–10 %“ werden ohne konkrete Datenbasis nicht verwendet.

## 9. Open-Source ML-Bibliotheken und Auswahl

Bibliotheken zunächst anhand Aufgabe, Lizenz der gewählten Version, Binärplattform,
Ressourcenbedarf und zeitlicher Prüfbarkeit auswählen. Eine einfache pip-Installation
auf einer Entwicklungsmaschine belegt keine HAOS-Lauffähigkeit.

[Ensembles und Frameworks](ensemble_hybrid_solar_forecasting.md) ordnet zusätzliche
Werkzeuge ein; [Datenquellen](solarprognose_datenquellen_feature_engineering.md)
trennt Forecastvintage, Beobachtung und Reanalysis. Die Integrationspins stehen im
[Manifest](custom_components/adaptive_solar/manifest.json), nicht in dieser Methodenauswahl.

## Empfohlene Vorgehensweise für dieses Projekt

Zuerst Quellen und bestehende Physik-/Residualpipeline qualifizieren. Einen Kandidaten
gegen die unveränderte Referenz mit identischen ausgabezeitlich verfügbaren Eingaben
prüfen. Modell-/Featureauswahl benötigt eigene Trainings-/Validierungsblöcke;
abschließende Prüftage nicht wiederholt zum Tuning verwenden. Metriken nach Einheit,
Tageslicht, Horizont und Ausgangsstufe getrennt berichten. Der
[Validierungsplan](docs/validierung.md) definiert den separaten prospektiven
Vergleich gegen Helios und Open-Meteo Solar.

## Quellen und Nachvollziehbarkeit

Alle Methodenverweise stehen direkt an der jeweiligen Aussage. Die Quellen sind
Bibliotheks-/Methodenprimärquellen; aus ihnen werden keine lokalen PV-Fehlerwerte
abgeleitet. Quantifizierte Literaturresultate können ergänzt werden, sobald Paper,
Datensatz, Messgrenze, Metrik, Forecastvintage und Vergleichsbaseline eindeutig
zugeordnet und reproduzierbar dokumentiert sind.
