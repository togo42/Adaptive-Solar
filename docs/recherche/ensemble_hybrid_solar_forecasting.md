# Ensemble-Methoden und hybride Modelle für Solarprognosen

Stand: 26.10.2026. Quellenbezogener Methodenüberblick; keine Rangliste und keine
Genauigkeitszusage für eine konkrete Anlage. Die früheren pauschalen Prozentgewinne
und nicht eindeutig identifizierten Paperverweise wurden entfernt. Ein
Methodennachweis ist kein gemessener PV-Prognosevorsprung. Die konkrete Umsetzung
steht im [Implementierungsvertrag](../technik/implementation-contract.md).

## 1. Ensemble-Methoden (Bagging, Boosting, Stacking) für Solar

Bagging mittelt Modelle aus verschiedenen Stichproben, Boosting ergänzt schrittweise
weitere Regressoren, Stacking lernt eine Kombination aus Vorhersagen mehrerer Modelle.
Die [scikit-learn-Dokumentation](https://scikit-learn.org/stable/modules/ensemble.html)
beschreibt diese Verfahren und ihre Implementierungen. Keines ist allein durch
seine Modellklasse besser als eine passende Persistenz- oder Physikbaseline.

Bei Zeitreihen muss auch das Training eines Stacking-Metamodells ohne Zukunftsdaten
erfolgen. Eine zufällige Standard-Cross-Validation ist dafür kein geeigneter Beleg.
[TimeSeriesSplit](https://scikit-learn.org/stable/modules/generated/sklearn.model_selection.TimeSeriesSplit.html)
ist ein Werkzeug für geordnete Splits; überlappende Zielintervalle, Empfangszeiten
und lokale Zieltage brauchen zusätzliche Prüfungen.

Adaptive Solar verwendet Gradient Boosting auf Residuen, aber kein Stacking.
Seine Wetterbaseline ist ein separates arithmetisches Mittel verfügbarer Mitglieder.

## 2. Physikalisch-informierte neuronale Netze (PINNs) für PV

PINNs verknüpfen ein Netztraining mit physikalischen Gleichungsresiduen. Eine
methodische Primärquelle ist Raissi, Perdikaris und Karniadakis,
[Physics Informed Deep Learning, Part I (2017)](https://arxiv.org/abs/1711.10561).
Diese Arbeit ist kein PV-Benchmark und belegt keinen bestimmten Prognosegewinn.

Für PV wären geeignete Gleichungen, Messgrenzen und Verlustannahmen festzulegen.
Eine weich gewichtete Lossfunktion garantiert nicht automatisch physikalisch
zulässige Ausgaben oder bessere Extrapolation. Adaptive Solar implementiert kein
PINN, sondern einen expliziten Physikpfad mit begrenzter Residualkorrektur.

## 3. Kombination aus NWP und ML

Eine Physikbaseline berechnet PV-Leistung aus prognostiziertem Wetter und Anlage.
Ein Residualmodell lernt später verfügbare Abweichungen. Für nachvollziehbare
Kandidaten lassen sich [pvlib](https://pvlib-python.readthedocs.io/) und ein
[GradientBoostingRegressor](https://scikit-learn.org/stable/modules/generated/sklearn.ensemble.GradientBoostingRegressor.html)
kombinieren. Die API-Dokumentationen belegen Funktionen, keinen konkreten PV-Skill.

Entscheidend sind archivierte ausgabezeitlich bekannte Features. ERA5 oder ein
nachträglich zusammengesetzter Wetterverlauf sind keine damalige Day-ahead-Ausgabe.
Fehlende Zählerintervalle dürfen nicht durch eine Physikschätzung zu Lernlabels
werden. Der [Datenquellenleitfaden](solarprognose_datenquellen_feature_engineering.md)
trennt die Datentypen.

## 4. Multi-Model Ensemble (verschiedene Wettermodelle kombinieren)

Mehrere Wettermodelle können gemittelt oder gewichtet werden. Das
[Open-Meteo-APIangebot](https://open-meteo.com/en/docs) unterscheidet Modelle,
Variablen, Horizonte und Intervalle. Gemeinsame Ausgangsdaten und `best_match`
verhindern die pauschale Annahme unabhängiger Mitglieder.

Vor einem Vergleich müssen Zielintervalle, Empfang und Modellkohorten zusammenpassen.
Ein Zusatzmodell kann Werte verändern oder bei lokalen Korrekturen zusätzliche
Unterstützung verlangen. Ob dies nützt, ist standortbezogen zu messen. Der Spread
ist zunächst ein deskriptiver Modellunterschied und kein kalibriertes P10/P90-Band.

## 5. Transfer Learning für PV-Prognose

Transfer Learning übernimmt Teile eines bereits trainierten Modells und passt sie
an eine neue Aufgabe an; die [Keras-Anleitung](https://keras.io/guides/transfer_learning/)
beschreibt den allgemeinen Ablauf. Für PV bleiben Unterschiede in Geometrie,
Sensorik, Wetter, Zeitbasis und Abregelung zu prüfen. Fremde Historie kann schaden;
ein Trainingszeit- oder Fehlergewinn ist ohne passenden Versuch nicht quantifiziert.

Adaptive Solar lädt keine fremden ausführbaren Modellobjekte. Es rekonstruiert lokale
Residualmodelle aus den eigenen archivierten Zeilen. Transfer Learning wäre eine
neue Modellpolitik mit eigenem Prüfplan, kein vorhandenes Feature.

## 6. Unsicherheitsquantifizierung (Quantile Regression, Conformal Prediction)

Quantilregression schätzt verschiedene Zielquantile; das
[scikit-learn-Beispiel](https://scikit-learn.org/stable/auto_examples/ensemble/plot_gradient_boosting_quantile.html)
zeigt Modellierung und empirische Coverageprüfung. Angelopoulos und Bates erklären
[Conformal Prediction (2021/2022)](https://arxiv.org/abs/2107.07511) einschließlich
Annahmen und Erweiterungen für Verteilungsänderungen/Zeitreihen.

Die klassischen marginalen Coverageaussagen setzen insbesondere geeignete
Austauschbarkeit voraus. Saisonwechsel, serielle Abhängigkeit und standortspezifische
Regime erlauben keine ungeprüfte Garantie für zukünftige PV-Intervalle.
Punktweise Coverage ist außerdem keine gemeinsame Tagespfad-Coverage.

Adaptive Solar verwendet empirische absolute Fehlergrenzen aus eigenen gehaltenen
Kalibrierblöcken. Sie sind keine zertifizierten P10/P90-Quantile; nach lokalen
Korrekturen können Grenzen entfallen. Details stehen im Implementierungsvertrag.

## 7. Online Learning / Adaptive Modelle

Inkrementelles Lernen aktualisiert Modelle mit eintreffenden Daten; die offizielle
[River-Dokumentation](https://riverml.xyz/) beschreibt dazu Werkzeuge. Jede Aktualisierung
braucht die tatsächlich verfügbare Zielmessung. Ein wiederveröffentlichteter alter
Zählerstand ist kein neues physisches Label.

Adaptive Solar nutzt statt inkrementeller Einzelupdates rekonstruierte Batchmodelle
mit eigener chronologischer Prüfung. Online Learning könnte Anpassung beschleunigen,
muss aber gegen eine unveränderte Referenz und auf Vergessen/Drift untersucht werden.

## 8. Open-Source Frameworks (mlforecast, Darts, sktime, tsai)

| Framework / Primärdokumentation | Mögliche Rolle | In Adaptive Solar enthalten? |
| --- | --- | --- |
| [mlforecast](https://nixtlaverse.nixtla.io/mlforecast/) | Tabellarische Forecastpipelines, Lags und Backtesting | Nein |
| [Darts](https://unit8co.github.io/darts/) | Statistische und neuronale Forecastmodelle | Nein |
| [sktime](https://www.sktime.net/en/stable/) | Schnittstellen und Evaluation von Zeitreihenmodellen | Nein |
| [tsai](https://timeseriesai.github.io/tsai/) | Deep Learning für Zeitreihen | Nein |
| [scikit-learn](https://scikit-learn.org/stable/) | Residualregressor und numerische Lernbausteine | Ja |

Eine Installierbarkeit per pip beweist keine native HAOS-Kompatibilität. Vor einer
zusätzlichen Abhängigkeit deren konkrete Version, Lizenz, Binärverfügbarkeit und
Ressourcenbedarf prüfen. Es werden keine pauschalen Modellzahlen, Arbeitszeiten
oder Genauigkeitsgewinne aus diesen Frameworks abgeleitet.

## Zusammenfassung: prüfbarer Einstieg

Für dieses Projekt zuerst die implementierte Physik-/Residualpipeline und ihre
Messquellen qualifizieren. Anschließend einzelne Kandidaten mit gleichen archivierten
Eingaben, eingefrorenen Kriterien und unabhängigen Prüfblöcken vergleichen. Der
[prospektive Validierungsplan](../entwicklung/validierung.md) trennt diesen Feldnachweis von
Methodenliteratur und lokalen Softwaretests. Eine automatische Umsetzung der hier
beschriebenen Alternativen ist daraus nicht beauftragt.
