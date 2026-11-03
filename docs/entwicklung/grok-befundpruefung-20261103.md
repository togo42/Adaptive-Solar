# Prüfung der Grok-Befunde vom 03.11.2026

Historischer Prüfstand vor den anschließenden
[Korrekturen der offenen Themen](grok-befundkorrekturen-20261103.md).

Geprüfte Implementierung: `4a74f4b4fab52b48d0a070463f8b1f64eedf9dd8`. Drei Subagenten und eine anschließende Gegenprüfung haben sämtliche **41 Einzelmeldungen aus zwölf Berichten** auf **35 eigenständige Themen** abgebildet. Doppelte Meldungen werden gemeinsam bewertet. Dieser Auftrag prüft und dokumentiert; er verändert keine funktionale Implementierung, produktive Konfiguration oder Qualitätsregel.

Grok-Meldungen sind Prüfkandidaten. Maßgeblich sind tatsächliche Aufrufpfade, bestehende Verträge und reproduzierbares Verhalten. Es wurden ausschließlich lokale synthetische Daten und installierte Testabhängigkeiten verwendet. Eine Betroffenheit produktiver Anlagen wurde in diesem Audit nicht erhoben.

## Inhalt

- [1. Ergebnis und Bedeutung der Urteile](#1-ergebnis-und-bedeutung-der-urteile)
- [2. Vorrangige bestätigte technische Punkte](#2-vorrangige-bestätigte-technische-punkte)
- [3. Vollständige Befundmatrix](#3-vollständige-befundmatrix)
- [4. Nachweismethode und Grenzen](#4-nachweismethode-und-grenzen)
- [5. Korrekturrichtungen](#5-korrekturrichtungen)

## 1. Ergebnis und Bedeutung der Urteile

| Urteil | Themen | Bedeutung |
| --- | ---: | --- |
| Bestätigt | 9 | Vier technische beziehungsweise fachliche Fehler und fünf aktuelle Dokumentations-/Statusfehler. |
| Teilweise bestätigt | 14 | Ein Mechanismus oder Teilvorwurf stimmt; behauptete Wirkung, Erreichbarkeit oder vorgeschlagene Lösung ist eingeschränkt. |
| Widerlegt | 9 | Fehlerannahme widerspricht Code, Schutzpfad oder ausdrücklich geltendem Vertrag. |
| Bereits behoben | 3 | Ursprünglicher Befund war richtig; Korrektur im geprüften Stand erneut bestätigt. |

Kein Originalvorkommen ist unzugeordnet. „Teilweise“ bedeutet keine pauschale Freigabe und auch keinen Auftrag, die gesamte Grok-Empfehlung umzusetzen. Insbesondere dürfen korrekte Sicherheitsregeln oder ausdrücklich historische Texte erhalten bleiben.

## 2. Vorrangige bestätigte technische Punkte

### Q2: Qualitätswiderruf reicht nicht über das aktuelle Capturefenster

Ein später belegter Producer-, Konfigurations- oder Generationswiderspruch wird erkannt. Die negativen Stundenmasken werden aber nur für das aktuelle Abfragefenster publiziert. In einem vollständigen synthetischen v2-Pfad mit 80 beobachteten Zielstunden und späterer 72-Stunden-Ableitung bleibt deshalb eine ältere positive Stunde außerhalb des neuen Fensters auswertbar.

Wichtig ist die Eingabeauswahl: Bei einer alten Aufnahme, die außerdem eine neu negativ maskierte Stunde enthält, bricht der Reader bereits mit `CaptureError` ab. Der stille Restannahmefall ist für disjunkte Captures reproduziert. Eine periodenweite explizite Qualitätsrevision muss auch solche alten Stunden erreichen. Es wurden keine produktiven positiven Labels untersucht.

### H1: HA-Setup räumt nach späten Ausnahmen unvollständig auf

In Tests mit echtem HA Core bleiben nach einer Ausnahme bei der Dienstregistrierung zehn reale Sensorentitäten an einem geschlossenen Coordinator. Eine injizierte Commit-Ausnahme lässt zusätzlich drei Dienste und Messlistener aktiv. Ein natives `async_reload` wiederholt das Setup und verdoppelt Messsubscriptions. Eine Ausnahme in `async_close` kann die Dienstabmeldung verhindern.

HA bereinigt den Optionslistener bereits selbst; doppelte Sensor-IDs werden abgefangen. Nachgewiesen sind zurückbleibende Plattformen und doppelte Messlistener. Ein natürlich auftretender Speicherfehler an genau der injizierten Commitstelle wurde nicht behauptet.

### H7: EPS-Auswertung deklariert gemischte Messgrenzen nicht

Der optionale Offlinepfad `replay_archive.py --probabilities --site-json` summiert AC- und DC-Stufen und kann Roh- sowie biaskorrigierte Scores erzeugen. Der Bericht benennt die gemischte Messgrenze nicht. Der native Energy-Pfad lehnt dieselbe Mischkonfiguration ab.

Eine ausdrücklich erklärte Summe unterschiedlicher Erzeugungsausgänge kann sinnvoll sein. Belegt ist die fehlende Deklaration beziehungsweise Prüfung im EPS-Scoringvertrag; konkrete physische Doppelzählung oder ein falsch gewählter produktiver Istzähler wurde nicht behauptet.

### P4: Früher Bias-Shadow akzeptiert inkompatible Schattenextreme

Faktoren 0,4 und 0,6 sind jeweils mit dem letzten Holdoutanker 0,5 kompatibel. Der Shadow akzeptiert dadurch eine Spannweite von 0,2 und meldet `shadow_ready`. Ein Repro mit 56 regulär verbundenen Lernzeilen ergibt einen Gain von 0,9388889 und einen Shadow-Kandidaten von 938,8889 W. Der normale ResidualLearner prüft zusätzlich die gesamte Spannweite gegen 0,1.

Die Wirkung betrifft den separaten Shadow-/Vergleichsarm. Veröffentlichte operative Forecastpunkte werden dadurch nicht verändert. Ein zusätzlicher Mediananker allein behebt den Extremfall nicht; benötigt wird die Familien-/Spannweitenprüfung.

## 3. Vollständige Befundmatrix

Originalkürzel: **G1** bezeichnet die Kandidatenmeldungen zum Stand `74125a9`, **G2** die abschließende Serie zu `e279aa6`, **G3** die zusätzliche Schnittstellenprüfung desselben Standes. G1 hatte einen später behobenen Transportauditfehler bei nativen Startmetadaten und gilt nicht als akzeptiertes Review. Die hier dokumentierten Urteile beruhen auf unabhängiger Primärprüfung.

### Qualität, Messdaten und Zeit

| ID / Original | Urteil | Thema und Primärergebnis | Primärquellen |
| --- | --- | --- | --- |
| **Q1** · G1/P1/AS-002, G3/A/AS-001 | teilweise bestätigt | **Zeitfilter, Originaldeltagrenze und Ereignishash**: As-of-/Bindungsfilter greifen erst nach semantischen Hartprüfungen: auch nicht verwendbare spätere/irrelevante Originalpayloads brechen den öffentlichen und den Offlinepfad ab. Überlange native Originaldeltas sind dagegen bereits producerseitig ausgeschlossen. Zukunftsabhängiger Eingabehash ist reproduziert, aber keine Änderung fachlicher Masken und kein alleiniger Look-ahead-Nachweis. Der behauptete stille Altlabel-Fallback ist bei direkter Mitübergabe des Fehlercaptures widerlegt. | [actual_quality.py](../../custom_components/adaptive_solar/core/actual_quality.py), [istwert-qualitaetsadapter.md](../archiv/istwert-qualitaetsadapter.md) |
| **Q2** · G2/I/AS-001 | bestätigt | **Periodensperre über Capturefenster**: Periodenweiter Konfigurations-/Producer-/Generationswiderspruch wird erkannt, aber nur innerhalb start/end als negative Stundenmaske publiziert. Der Reader nutzt ausschließlich Masken; außerhalb des aktuellen Fensters bleibt eine alte disjunkte positive Stunde akzeptiert, entgegen dem dokumentierten periodenweiten Widerruf. | [actual_quality.py](../../custom_components/adaptive_solar/core/actual_quality.py), [istwert-qualitaetsadapter.md](../archiv/istwert-qualitaetsadapter.md) |
| **Q3** · G3/A/AS-002 | widerlegt | **Abregelung in Originaldeltas**: Der behauptete false-positive Pfad übersieht den Producervertrag: qualified_interval wird erst nach nachgewiesen sicherem Abregelungszustand exportiert. Eine vor Zielbeginn aktive und durchgehend aktive/unknown/restored Phase liefert keine Originaldeltas und folglich keine freigegebene Stunde. Das false der positiven Maske ist eine Aussage aus diesem qualifizierten Support. | [coordinator.py](../../custom_components/adaptive_solar/coordinator.py), [istwert-qualitaetsadapter.md](../archiv/istwert-qualitaetsadapter.md) |
| **Q4** · G3/A/AS-003 | teilweise bestätigt | **Zeitordnung von TrainingSample**: Dataclass und Mittelpunkthelper akzeptieren beziehungsweise kappen die genannten Zeitfälle tatsächlich. Die behauptete Verwendung als Lernzeile ist im echten Pfad widerlegt: join_training/MeasurementIndex sowie ResidualLearner.fit und EarlyBiasShadow.fit prüfen die Prospektivität und Finalisierung vor Nutzung. | [models.py](../../custom_components/adaptive_solar/core/models.py), [measurement-learning.md](../technik/measurement-learning.md) |
| **Q5** · G1/P4/AS-002 | teilweise bestätigt | **Baseline im Intervallintegrator**: Fehlende baseline_w-Prüfung in integrate_original ist bestätigt: True wird zu 1 W, NaN/Inf und Werte außerhalb der Dataclassgrenzen werden arithmetisch weitergereicht. Ein Boolean erreicht auch den Endpunktjoin bei direkter unvalidierter Archiveinspeisung. Der native Erzeuger- und Restoreweg lässt diese Zeilen nicht zu. | [measurement.py](../../custom_components/adaptive_solar/core/measurement.py), [measurement-learning.md](../technik/measurement-learning.md) |

### Physik, Schatten, Bias und Nowcast

| ID / Original | Urteil | Thema und Primärergebnis | Primärquellen |
| --- | --- | --- | --- |
| **P1** · G2/P3/AS-001 | widerlegt | **Optionale Physik-Teilintegration**: Die Ausfälle sind reproduzierbar, entsprechen aber der ausdrücklich dokumentierten Fail-closed-Policy für optionale Teilintegration. Ein funktionaler Mittelpunktfallback oder Komponentenclip ist kein aus diesem Befund begründeter Fix. | [physics.py](../../custom_components/adaptive_solar/core/physics.py), [physics-learning-options.md](../technik/physics-learning-options.md) |
| **P2** · G1/P3/AS-001 | teilweise bestätigt | **Messgültigkeitsphase im Schatten-Replay**: Bestätigte unabhängige Replay-Prüflücke: ein falsches false-Flag wird trotz Power vor validity-on akzeptiert, auch im vollständigen synthetischen Replay. Der normale Koordinator sperrt diese Kombination bereits; eine produktive Tabellenvergiftung ist damit nicht belegt. | [shade_replay.py](../../custom_components/adaptive_solar/core/shade_replay.py), [measurement-validity.md](../technik/measurement-validity.md) |
| **P3** · G2/P3/AS-002 | teilweise bestätigt | **Schattenfallback: Alter und Übergrenze**: Der optionale Beobachtungs-Fallback sperrt eine frische klare Probe wegen 16 Minuten alter Curtailment-/Übergrenzenbelege. Übergrenze plus manuell falsches false-Flag schreibt ebenfalls; dieser stage_input verletzt aber den expliziten Aufrufervertrag und wird durch beide normalen Aufrufer ausgeschlossen. | [shade_learning.py](../../custom_components/adaptive_solar/core/shade_learning.py), [implementation-contract.md](../technik/implementation-contract.md) |
| **P4** · G1/P3/AS-003 | bestätigt | **Schattenphasen im frühen Bias-Shadow**: Shadow prüft alle Faktoren nur gegen den letzten Holdoutanker. .4 und .6 passen jeweils zu .5 und ergeben shadow_ready trotz Spannweite .2. Der reguläre ResidualLearner verlangt zusätzlich max-min <= .1; diese Familienprüfung fehlt im Shadow. | [early_bias.py](../../custom_components/adaptive_solar/core/early_bias.py), [early-bias-shadow.md](../technik/early-bias-shadow.md) |
| **P5** · G2/P4/AS-002 | widerlegt | **Gewichtung mehrerer Forecast-Origins**: Die behauptete Mehrfachgewichtung derselben Iststunde übersieht _weights: zwei Origins derselben Stunde bekommen je 1800 Sekunden, gemeinsam 3600. Selektive zusätzliche äquivalente Origins für die Low-Ratio-Stunde verändern Gain, MAE und eindeutige Belegstunden nicht. | [early_bias.py](../../custom_components/adaptive_solar/core/early_bias.py), [early-bias-shadow.md](../technik/early-bias-shadow.md) |
| **P6** · G1/P5/AS-004 | teilweise bestätigt | **Fehlende Phasenschlüssel im Nowcastverlauf**: Leeres/partielles phases lässt im isolierten Verlauf alte Belege und Phasenschlüssel stehen. Der einzige produktive Aufrufer erzeugt phases jedoch vollständig für jede konfigurierte Stufe; die behauptete normale Nowcast-Verletzung ist dadurch nicht erreichbar. | [nowcast.py](../../custom_components/adaptive_solar/core/nowcast.py), [physics-learning-options.md](../technik/physics-learning-options.md) |
| **P7** · G1/P5/AS-005 | teilweise bestätigt | **Synthetisches CLI-Wetter und Zeitzonen**: Drei Mechanismen geprüft: Demo erzeugt nur erstes Modell (aber zweites explizit unavailable), speichert Clear-Sky-Mittelpunktwerte als Intervallnäherung und verliert bei halben/viertel Stundenoffsets 15/30 Minuten am Horizontende. Der lückenhafte Demo-Horizont ist ein echter CLI-Randfall; Produktionswetter wird nicht betroffen. | [forecast.py](../../scripts/forecast.py), [README.md](../../README.md) |

### HA, Persistenz und Wahrscheinlichkeiten

| ID / Original | Urteil | Thema und Primärergebnis | Primärquellen |
| --- | --- | --- | --- |
| **H1** · G1/P5/AS-003, G2/P5/AS-001 | bestätigt | **Rollback nach fehlgeschlagenem HA-Setup**: Fehlendes Setuprollback mit echtem HA Core reproduziert: nach Plattformweitergabe bleiben 10 Sensoren; Commit-Ausnahme lässt Dienste und Messlistener aktiv. Native Wiederholung per async_reload verdoppelt beide Messlistener. Eine zusätzliche close-Ausnahme verhindert die Dienstabmeldung. | [__init__.py](../../custom_components/adaptive_solar/__init__.py), [implementation-contract.md](../technik/implementation-contract.md) |
| **H2** · G2/P4/AS-001 | widerlegt | **probatio-Import**: probatio ist die native Schemaabhängigkeit des installierten HA Core 2026.10.4. services.py importiert erfolgreich; alle drei Dienste werden real registriert. Der vorgeschlagene Wechsel auf voluptuous ist unbegründet. | [services.py](../../custom_components/adaptive_solar/services.py), [pyproject.toml](../../pyproject.toml) |
| **H3** · G1/P3/AS-006 | teilweise bestätigt | **Falsches Formularfehlerfeld**: Leere weather_models passieren den nativen HA-Selector und erzeugen tatsächlich den falschen Zeitzonenfehler. Ungültige Integertexte werden bereits vom Schema des HA-Flowmanagers abgelehnt; deren Fehlzuordnung lässt sich nur bei direktem Handleraufruf reproduzieren. | [config_flow.py](../../custom_components/adaptive_solar/config_flow.py), [test_config_flow.py](../../tests/test_config_flow.py) |
| **H4** · G2/P5/AS-002 | teilweise bestätigt | **Toleranz gespeicherter Tagesstartwerte**: Beide Validatoren gestatten explizit 110 % der ursprünglichen Cap. Auf 23/24/25-Stunden-Tagen passieren Tageswerte und jede Stundenzeile diese Grenze; native Store-Ladung und Operatorimport veröffentlichen den überhöhten Tageswert. Der Zusatz über gepaarte Vergleiche ist für die vorhandenen Evaluationspfade nicht belegt. | [snapshots.py](../../custom_components/adaptive_solar/snapshots.py), [forecast-repairs.md](../technik/forecast-repairs.md) |
| **H5** · G1/P4/AS-001, G2/P4/AS-004 | teilweise bestätigt | **Unvollständige Ensemblefamilien mischen**: combine_families verliert den expliziten incomplete_cohort-Status und excluded_members. Die Gesamtzählung member_count/expected_members bleibt jedoch sichtbar. Volles Familiengewicht ist nach dokumentierter Policy unabhängig von Mitgliederzahl und daher nicht isoliert ein nachgewiesener Rechenfehler. | [probability.py](../../custom_components/adaptive_solar/core/probability.py), [archivbetrieb.md](../archiv/archivbetrieb.md) |
| **H6** · G1/P4/AS-003 | teilweise bestätigt | **Capturestatus eines Teilensembles**: Collector meldet bei 1/51 oder 50/51 nutzbaren Mitgliedern available, Lauf complete und Exit0. Alle fehlenden/abgelehnten Mitglieder sowie exakte Rohbytes bleiben erhalten. Das bestätigt die Beschreibung des Capturestatus, beweist aber keinen Fehler der nachgelagerten Ensemblevollständigkeit: Standardreplay verlangt separat Quorum1.0. | [capture_weather.py](../../scripts/capture_weather.py), [archivbetrieb.md](../archiv/archivbetrieb.md) |
| **H7** · G2/P4/AS-003 | bestätigt | **AC-/DC-Mischsumme im EPS-Replay**: Optionales EPS-Replay summiert alle Stufen auch eines gemischten AC/DC-Sites, gibt Q10/Q50/Q90 und Scores sowie optionale Biaskalibrierung aus und benennt die gemischte Messgrenze im Bericht nicht. Der unabhängige native Energy-Pfad lehnt dieselbe gemischte Konfiguration ab. | [replay_archive.py](../../scripts/replay_archive.py), [implementation-contract.md](../technik/implementation-contract.md) |

### Archiv, Auswertung, Timer und Native-Tests

| ID / Original | Urteil | Thema und Primärergebnis | Primärquellen |
| --- | --- | --- | --- |
| **R1** · G1/P1/AS-001 | widerlegt | **Mehrere Gzip-Member**: Python und echtes Rust akzeptieren dasselbe gültige Original aus zwei Gzip-Membern: identische Bytes, kein Native-Fallback. | [archive.py](../../custom_components/adaptive_solar/core/archive.py), [native-qualitaetsbackend.md](../archiv/native-qualitaetsbackend.md) |
| **R2** · G1/P1/AS-003 | bereits behoben | **Journalretention bei rückdatiertem Empfang**: Historischer Fehler erneut reproduziert: Im alten Code verschwindet eine junge Sequenz vor einer rückdatierten Sequenz. Der aktuelle Code erhält alle drei Ereignisse. | [archive.py](../../custom_components/adaptive_solar/core/archive.py), [archive-storage-contract.md](../archiv/archive-storage-contract.md) |
| **R3** · G1/P2/AS-001 | bereits behoben | **Energie-Gates mit unvollständigen Origins**: Der alte Stand meldet bei 30 vollständigen Tagen mit nur 2 % Vorteil plus einem leichten unvollständigen Tag fälschlich Verbesserung. Der aktuelle Stand verweigert sie bei denselben 61 Rohpaaren. | [evaluation.py](../../custom_components/adaptive_solar/core/evaluation.py), [validierung.md](validierung.md) |
| **R4** · G1/P3/AS-004, G2/P3/AS-003 | widerlegt | **Modellvorlauf und Vergleichsvorlauf**: Modell und Guard verwenden den ursprünglichen Ausgabevorlauf; Stratum und Gesamtscoring verwenden den dokumentierten gemeinsamen Vergleichscutoff. Unterschiedliche Bins sind hier korrekt. | [support_evaluation.py](../../custom_components/adaptive_solar/core/support_evaluation.py), [implementation-contract.md](../technik/implementation-contract.md) |
| **R5** · G1/P4/AS-004 | teilweise bestätigt | **Quellenwahl beim Vergleichsarchiv**: Die allgemeinen Defaults ergeben für ein alleiniges internes Vergleichsarchiv null Paare; explizite Quellenwahl ergibt ein Paar. Fehlende Quellen und negative Freigabe werden sichtbar berichtet. Stilles Fehlscoring ist widerlegt. | [evaluate.py](../../scripts/evaluate.py), [model-comparison-archive.md](../technik/model-comparison-archive.md) |
| **R6** · G1/P5/AS-001 | teilweise bestätigt | **Lokale systemd-Kalender und DST**: Groks DST-Erklärung ist falsch: Im Frühjahr bleibt die physische Kadenz konstant, im Herbst gibt es keine Dopplung. systemd 259.9 überspringt jedoch die zweite Faltstunde: 65 Minuten HA-Abstand, zwei Stunden Wetter-/Observations-Abstand. UTC-Kontrolle: fünf Minuten. | [adaptive-solar-archive-ha.timer](../../deploy/adaptive-solar-archive-ha.timer), [archiv-host-installation.md](../archiv/archiv-host-installation.md) |
| **R7** · G1/P5/AS-002 | widerlegt | **Historisches und aktuelles CI-Orakel**: Historische Tests prüfen absichtlich einen eingefrorenen Kompaktvertrag. Zusätzlich verwenden Readerbaseline und echter Produktionsvergleich den aktuellen Checkout und dessen neun Quellen. Die CI ist gegenüber aktuellem Pythoncode nicht blind. | [tests.yml](../../.github/workflows/tests.yml), [native-qualitaetsbackend.md](../archiv/native-qualitaetsbackend.md) |

### Dokumentation und historische Geltungsbereiche

| ID / Original | Urteil | Thema und Primärergebnis | Primärquellen |
| --- | --- | --- | --- |
| **D1** · G1/P3/AS-002 | teilweise bestätigt | **Abdeckung, Rand- und Innenlücken**: 92 % Abdeckung und 180 Sekunden Randgrenze sind weiterhin aktive Regeln. Die 1-/5-Sekunden-Grenzen gelten zusätzlich für innere Lücken. Die Anleitung erklärt diese Ergänzung nicht; Groks vorgeschlagene Historisierung der alten Regeln wäre falsch. | [learning.py](../../custom_components/adaptive_solar/core/learning.py), [measurement-learning.md](../technik/measurement-learning.md) |
| **D2** · G1/P3/AS-005 | bereits behoben | **Zahl der systemd-Reviewdateien**: Die alte Dokumentation nannte acht statt zwölf Vorlagen, während der Reviewcode bereits alle zwölf einbettete. Die aktuelle Dokumentation wurde korrigiert. | [validierung.md](validierung.md) |
| **D3** · G1/P3/AS-007 | widerlegt | **Historische Viertelstunden-Ersetzung**: Der Ersetzungsbullet gehört ausdrücklich zur historischen Paketabnahme von 0.2.12. Der aktuelle Nachtrag friert die erste Probe ein; der alte Tag ersetzte tatsächlich. Kein Widerspruch im jeweiligen Geltungsbereich. | [adaptive-solar-verschattung.md](../technik/adaptive-solar-verschattung.md) |
| **D4** · G1/P4/AS-005, G2/P4/AS-006 | bestätigt | **Datenschutz: Datenflüsse und Veröffentlichungsstand**: Der Datenschutztext nennt nur den Forecast-Endpunkt; der optionale Collector fragt auch den Ensemble-Endpunkt mit Koordinaten ab. Außerdem bezeichnet er in 0.2.21 veröffentlichte Profile noch als Vorbereitung. | [datenschutz.md](../anwendung/datenschutz.md), [release-0.2.21.md](../releases/release-0.2.21.md) |
| **D5** · G1/P4/AS-006, G2/P4/AS-005 | bestätigt | **Installations-/Upgradeanleitung**: Die Installationsanleitung bezeichnet sich als 0.2.20 und endet mit diesem Upgradeabschnitt. Die Zusammenfassung des 0.2.21-Upgrades fehlt. Allgemeiner HACS-Ablauf und Link zur aktuellen Hostanleitung bleiben gültig. | [installation.md](../anwendung/installation.md), [release-0.2.21.md](../releases/release-0.2.21.md) |
| **D6** · G2/P3/AS-004 | bestätigt | **Versionskopf der Bedienung**: Der Bedienungskopf nennt 0.2.18 und dessen Releasehinweise, enthält aber das Nachtprofil aus 0.2.21. Der Dokumentationseinstieg nennt die aktuellen Anleitungen 0.2.21. | [bedienung.md](../anwendung/bedienung.md), [README.md](../README.md) |
| **D7** · G2/P3/AS-005 | bestätigt | **Versionskopf des Archivbetriebs**: Die Archivbetriebsanleitung nennt Funktionsumfang 0.2.18, beschreibt aber die später hinzugekommene fortlaufende quality_bindings-Aufnahme. Der ausgewiesene Geltungsbereich ist veraltet. | [archivbetrieb.md](../archiv/archivbetrieb.md), [README.md](../README.md) |
| **D8** · G2/P4/AS-007 | bestätigt | **Status des Messdatenvertrags**: Der aktuelle Messvertrag bezeichnet die Einheitenwechselregel als unveröffentlichten Kandidaten 0.2.20. Diese Version und 0.2.21 sind inzwischen veröffentlicht. | [measurement-learning.md](../technik/measurement-learning.md), [release-0.2.20.md](../releases/release-0.2.20.md) |
| **D9** · G2/P4/AS-008 | widerlegt | **Historische Schattenanalyse und Altersgrenze**: Die Analyse ist ausdrücklich historisch gegen 0.2.13; dieser Tag hatte keine Altersgrenze. Außerdem begrenzt die heutige 45-Tage-Regel die Anwendung und Freigabe, während ältere Rohproben gespeichert bleiben dürfen. | [adaptive-solar-analyse.md](../recherche/adaptive-solar-analyse.md), [datenschutz.md](../anwendung/datenschutz.md) |

### Zentrale Gegenbelege und Einschränkungen

- **Q1:** Semantische Prüfungen vor dem Zeitfilter können den öffentlichen Offlinepfad abbrechen. Änderungen am Hash vollständiger Eingabe-Envelopes sind ausdrücklich dokumentierte Rohprovenienz; im Repro bleiben Stundenmasken trotz gültiger späterer Ereignisse identisch. Ein fachlicher Look-ahead ist damit nicht nachgewiesen. Der native Tracker erzeugt keine Originaldeltas über 900 Sekunden.
- **Q3:** Ein vollständiger nativer HA-Zustand–Tracker–Export–Adapter–Normalisierungspfad erzeugt bei aktiver, unbekannter oder restaurierter Abregelung keine qualifizierten Deltas. Der klare Kontrollfall wird freigegeben.
- **Q4/Q5:** Permissive Dataclass beziehungsweise Helperannahmen sind real. Die untersuchten Join-/Fit-, Erzeuger- und Restore-Gates blockieren jedoch die behauptete normale Lernwirkung. Direkte unvalidierte Helfereingaben sind gesondert zu härten, falls sie unterstützt werden sollen.
- **P1:** Ausfälle der optionalen Teilintegration sind in der Physikoptions-Dokumentation ausdrücklich vorgesehen. Ein Mittelpunktfallback oder Komponentenclip würde die geltende Policy ändern. Nur ein zu weit gefasster lokaler Kommentar sollte präzisiert werden.
- **P2/P3/P6:** Repros belegen Replay-/Fallback-/Helperlücken. Der aktuelle normale Coordinator prüft Messgültigkeitsphasen, Übergrenzen und die vollständige Phasenliste bereits. Ein akzeptierter synthetischer Replay ist Integritäts-/Softwareevidenz, kein Authentizitätsnachweis des manipulierten Producer-Events.
- **P5:** Zwei Origins derselben Messstunde erhalten je 1.800 Sekunden Gewicht und zusammen 3.600 Sekunden. Selektive zusätzliche äquivalente Origins ändern Gain, Fehler und eindeutige Belegstunden im Repro nicht. Unterschiedliche Baselines können dagegen den Quotienten der gemittelten Forecastaufgabe verändern.
- **P7:** Bei UTC+05:30 und UTC+09:30 fehlen der synthetischen CLI 1.800 Sekunden am Horizontende, bei UTC+05:45 sind es 900 Sekunden. Berlin sowie 23-/25-Stunden-Tage sind abgedeckt. Das zweite Modell wird ausdrücklich als nicht verfügbar berichtet; der Mittelpunkt ist eine Demoapproximation.
- **H3:** Eine leere Modellliste ist über den echten Selector erreichbar und wird fälschlich als Zeitzonenfehler angezeigt. Ungültige Ganzzahltexte werden bereits von Selector und Flowmanager abgefangen. Nur ein direkter Handleraufruf unter Umgehung der HA-Schemaprüfung erreicht diese Fehlzuordnung.
- **H4:** 110 % der Grenze passieren tatsächlichen Import, Store und Sensor an 23-/24-/25-Stunden-Tagen. Eine Weitergabe dieser Werte in die gepaarten Vergleichsarme wurde nicht belegt; deren ComparisonArchive ist eigenständig.
- **H5/H6:** Mischung verliert expliziten Unvollständigkeitsstatus und ausgeschlossene Mitgliedsnamen, während Zählungen erhalten bleiben. Unabhängige Familiengewichte sind erklärte Policy. Ein Capture mit nur 1/51 Mitgliedern meldet zwar Exit 0, bewahrt aber Rohbytes und Missingness; das Standardreplay prüft separat Quorum 1,0. Captureabschluss und vollständige Kohorte brauchen unterscheidbare Begriffe.
- **R4:** Der Modellvorlauf 6,5 Stunden bleibt `6-24h`; nach einer Stunde Empfangsverzug ist der Vergleichsvorlauf 5,5 Stunden und sowohl Stratum als auch globales Scoring korrekt `0-6h`. Bereits getroffene Modell-/Guardentscheidungen werden dabei nicht neu berechnet.
- **R5:** Quellen werden im dokumentierten Auftrag ausdrücklich gewählt. Ohne passende Referenzen entstehen sichtbare Missingness, null Paare und eine negative Verbesserungsaussage. Automatisches Hinzufügen aller Archivarme würde eine bewusst gewählte Vergleichsfamilie verändern.
- **R6:** Lokale Kalender unter systemd 259.9 und Europe/Berlin zeigen im Herbst 65 Minuten HA-Abstand beziehungsweise zwei Stunden Wetter-/Observations-Abstand. Im Frühjahr bleiben physische UTC-Abstände fünf Minuten beziehungsweise eine Stunde. Ein lokaler täglicher Retentionstermin nach der Umstellungsstunde hat einen anderen Zweck als feste stündliche Abholkadenz. Produktive Datenverluste wurden nicht untersucht; Journale und Recorder-Nachholung können Messdaten erhalten.
- **R7:** Der historische Kompaktvertrag und das aktuelle Produktionsorakel sind zwei zusätzliche Prüfungen. Den eingefrorenen Vertrag durch die aktuelle Revision zu ersetzen zerstört dessen ausdrückliche Quellenbindung.
- **D1:** 92 % Abdeckung, maximal 180 Sekunden je fehlendem Rand und die 1-/5-Sekunden-Innenlückenbudgets gelten gleichzeitig. Ein zusammenhängender 56-Minuten-Block mit zwei Minuten Randverlust erfüllt die aktuellen Grenzen.
- **D3/D9:** Historische Paketabnahme und Analyse sind explizit als historisch bezeichnet und passen zu den Tags `v0.2.12` beziehungsweise `v0.2.13`. Auch heute dürfen ältere Schattenrohproben gespeichert bleiben, obwohl sie nach 45 Tagen nicht mehr zur Freigabe zählen.

## 4. Nachweismethode und Grenzen

Es wurden insgesamt **287 gezielte Pytestfälle ohne Skips** ausgeführt: 34 Qualität/Zeit, 169 vorhandene Physik-/Schatten-/CLI-Tests, 26 HA-/Wahrscheinlichkeitsproben, 15 gezielte Archiv-/Evaluationsregressionen, 42 echte historische Native-Differential-/Projektionsfälle und ein echter aktueller Native-Produktionsvergleich. Dazu kommen sieben zusätzliche Physik-/Schattenrepros, echte CLI-Gegenkontrollen, zwölf Kalenderfälle und Alt-/Neustand-Gegenproben.

Erfolgreiche Auditasserts können ausdrücklich das aktuelle Fehlverhalten bezeugen. Die Zahl bestandener Tests ist deshalb keine Fehlerfreiheits- oder Freigabeaussage. Es gab keine produktiven HA-/Hostabfragen oder Änderungen und keinen neuen externen Reviewtransfer in diesem Audit.

Für R2/R3 wurden die unveränderten ursprünglichen Git-Module aus `74125a9` in getrennten Modulnamensräumen gegen den aktuellen Stand ausgeführt:

| Gegenprobe | Alter Stand | Geprüfter Stand |
| --- | --- | --- |
| Junge Sequenz vor rückdatiertem Empfang | Nur jüngstes Ereignis bleibt; zwei verworfen | Alle drei Ereignisse bleiben |
| 30 vollständige Tage mit 2 % Vorteil plus unvollständiger leichter Tag | Verbesserung fälschlich wahr | Verbesserung falsch; dieselben 61 Rohpaare bleiben |

Bestehende aktuelle Regressionen lassen sich ohne private Betriebsdaten ausführen:

```bash
.venv/bin/python -m pytest -q tests/test_archive_store.py tests/test_evaluation.py \
  -k 'retention or capacity or mid_batch or incomplete_origin_day or energy_gate'
```

Der reale Nativevergleich benötigt zusätzlich ein explizit gebautes und gepinntes Modul gemäß [Native-Backendvertrag](../archiv/native-qualitaetsbackend.md). Kalender-Gegenprobe ohne Aktivierung eines Timers:

```bash
TZ=Europe/Berlin systemd-analyze calendar \
  --base-time="2026-10-25 01:45:00" --iterations=30 "*:00/5:00"
TZ=Europe/Berlin systemd-analyze calendar \
  --base-time="2026-10-25 01:45:00" --iterations=30 "*:00/5:00 UTC"
```

Die vollständigen synthetischen Eingaben, Feldprüfungen, Quellhashes, Einzelberichte und exakte 41→35-Zuordnung werden als ignorierte lokale Audit-Artefakte aufbewahrt. Die Tabellen und beschriebenen Gegenbeispiele sind der eigenständig verständliche öffentliche Ergebnisstand. Es wurden keine privaten Anlagenbeobachtungen übernommen.

## 5. Korrekturrichtungen

1. **Q2 und H1 zuerst:** Periodenwiderruf konsistent durch den Reader führen; HA-Setup einschließlich Forwarding, Diensten und Commit mit vollständigem Rollback absichern. Jeweils normale Fälle, Fehlerpfade und bestehende Historie regressieren.
2. **H7 und P4:** Messgrenzen des EPS-Scorings ausdrücklich deklarieren beziehungsweise trennen; vollständige Schattenfamilie statt bloßem Ankervergleich prüfen. Shadowwirkung und operative Prognose getrennt halten.
3. **Bestätigte Teilprobleme gezielt bearbeiten:** unter anderem Replaygültigkeitsprüfung, synthetisches CLI-Horizontende, Formularfehlermeldung, Snapshotimportgrenze und Ensemble-Statusweitergabe. Dabei bestehende Erzeuger-/Fit-/Replayguards und dokumentierte Gewichte erhalten.
4. **Fünf Dokumentations-/Statusfehler und D1:** heutige Geltungsbereiche und Datenflüsse nachführen. Historische Texte, korrekte 92-%-/180-Sekunden-Regeln sowie korrekt abgegrenzte Vergleichsfamilien erhalten.

Diese Reihenfolge ist eine aus der Prüfung abgeleitete Korrekturplanung. Sie ist kein Nachweis physischer Quellenqualität oder besserer Prognosen und erteilt keine produktive Änderungsfreigabe.
