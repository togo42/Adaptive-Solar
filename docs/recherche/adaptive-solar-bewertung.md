# Adaptive Solar Bewertung und Grundlage für Arbeitspakete

Stand: 27.10.2026. Codeabgleich gegen **0.2.12**, Releasecommit
`7c2b4be3315ebc062b5b09a8237f94649cf7d034`. Die Bewertung vom 26.10.2026
bezog sich auf 0.2.11, Commit `32d1d0e57e0a2be2c823e4f078c9c48a8fa4f320`;
Vergleichsbasis der ersten Bewertung war 0.2.8, Commit `0285445`.
Die [Analyse](adaptive-solar-analyse.md) beschreibt nun auch die Schattentabelle
und die erweiterten Refit-Auslöser von 0.2.12. Die Prioritäten bleiben
Planungshypothesen ohne neuen Güte- oder Ressourcenmessnachweis.

Der spätere lokale [Messdaten-Nachtrag](../technik/messintervalle-92-prozent.md) setzt die
ausdrücklich beauftragte Änderung auf 92 % und feste drei Minuten Randlücke
sowie Korrekturen der Messaufbereitung um. Dieser Text bleibt die Bewertung
der oben gebundenen Releasebasis; er behauptet damit keine Abnahme der
nachfolgenden Optimierungs- oder Benchmarkpakete.

**Ergebnis:** Die überarbeitete Analyse ist fachlich deutlich belastbarer. Sie
berücksichtigt die wesentlichen Einwände der ersten Bewertung. Vorrang haben eine
qualifizierte Messgrundlage, reproduzierbare Vergleiche und gemessene
Ressourcenkosten. Clearness-Index und zeitlich korrekt normalisierte
Nowcast-Glättung sind geeignete erste Modellversuche. Wettergewichte benötigen
zunächst Einzelmodellarchive; Lag-Features und probabilistische Erweiterungen
folgen bei ausreichender Datenbasis.

Die unten beschriebenen Pakete sind **historische Planungsvorschläge** zur
oben gebundenen Basis. Der damalige Status „offen“ ist kein aktueller
Umsetzungsstand: Seit 0.2.15 sind unter anderem Physik-/Nowcastkandidaten,
Bias-Shadow und Modellvergleichsarchive hinzugekommen; seit 0.2.16 der
Originaldatenexport. [Versionshinweise](../releases/README.md) und
[Implementierungsvertrag](../technik/implementation-contract.md) beschreiben
den heutigen Stand. Fachliche Abnahmekriterien und prospektiver Vergleich
bleiben von der Implementierung getrennt.

## 1 Änderungen seit der ersten Bewertung

| Bereich | Bestätigter neuer Stand | Konsequenz für die Planung |
| --- | --- | --- |
| Analyse | Unbelegte Gewinnversprechen, die pauschale Nowcast-Verschlechterung und das einfache Quorum wurden durch Prüfaufträge ersetzt. | Die frühere Top-3-Liste ist überholt; die neue Reihenfolge ist als Hypothese geeignet. |
| Messgültigkeit | Optionales `measurement_valid_entity_id`; ungültige Phasen sperren neue Energie- und Powerbeobachtungen. Wiederanlauf benötigt echte neuere Originalberichte. | Bestehende Schutzmechanismen verwenden und erhalten; kein neuer paralleler Qualitätsmechanismus nötig. |
| Eingangsqualität | Restaurierte numerische Werte werden für alle Eingangsklassen verworfen. Join-Diagnosen trennen zu kurze, nicht prospektive und bei Ausgabe angeschnittene Ziele. | Vor einer Modelländerung die konkreten Ablehnungsgründe auswerten. |
| Lernhistorie | Featurevertrag `beam-shade-table-v1`; separat gebundene Messhistorie, Tagesbeginn-Snapshots und Schattentabelle. | Neue Features brauchen eine explizite Vertragsänderung; physische und Schattenprovenienz bleiben unabhängig streng. |
| Physik | Morgen-/Abenddämpfung je String, nach Temperatur-/Stringverlustrechnung und vor gemeinsamem AC-/DC-Clip. | Physik und Konfiguration vor Vergleichen einfrieren; alte und neue Dämpfungsstände nicht unbemerkt zusammenlegen. |
| Anzeige | AS-UI-001 ist seit 0.2.10 umgesetzt, einschließlich Kompatibilitätsanzeigen bestehender Gesamt-Sensoren. | Kein neues offenes Optimierungspaket daraus ableiten. |
| Ensemble und ML | `core/engine.py` und `core/learning.py` berücksichtigen nun die gelernte Direktstrahl-Baseline und deren Stützung in Training, Holdouts und Vorhersage. | Mittelwert, Kohortenregeln, 13 Baumfeatures, Regimetrennung und Aktivierungsschwellen bestehen fort; Schattenphasen zusätzlich einfrieren und qualifizieren. |
| Refit | Die Fit-Signatur enthält neben Historienrevision und lokalem Tag die vollständig serialisierte Schattentabelle. | AS-OPT-02 muss auch neue/ersetzte Schattenaufnahmen bei unverändertem Median als mögliche Refit-Auslöser erfassen. |

Codebelege: [Coordinator](../../custom_components/adaptive_solar/coordinator.py),
[Physik](../../custom_components/adaptive_solar/core/physics.py),
[Datenklassen](../../custom_components/adaptive_solar/core/models.py),
[Sensorplattform](../../custom_components/adaptive_solar/sensor.py).
Verhaltenstests: [Messgültigkeit](../../tests/test_measurement_validity.py),
[Eingangsprüfung und Join-Diagnosen](../../tests/test_review_0_2_10.py),
[Dämpfung](../../tests/test_damping.py), [Gerätemigration](../../tests/test_device_migration.py).

## 2 Bewertung der Vorschläge

Prioritäten: **P0** schafft die Entscheidungsgrundlage; **P1** bezeichnet begrenzte
erste Versuche; **P2** folgt nach Daten- oder Nutzennachweis. Das erwartete Potenzial
ist eine Bewertung, kein gemessener Standortgewinn. Aufwand ist relativ zu diesem
Repository: S = eng begrenzt, M = mehrere Module oder Nachweise, L = neuer
Archiv-/Auswertungspfad. Es handelt sich nicht um Terminzusagen.

| Vorschlag aus der Analyse | Bewertung | Nächster Schritt |
| --- | --- | --- |
| Quellen, Baseline und prospektive Archive qualifizieren | P0, notwendig | AS-OPT-01 |
| Refitkosten und Nowcast-Ausschlüsse messen | P0, notwendig | AS-OPT-02; vorhandene Diagnosen ergänzen |
| Refit-Throttle | P1, nur bei relevantem gemessenem Aufwand | AS-OPT-04; kein garantierter Gleichlauf der Prognosen |
| Clearness-Index | P1, geeignete erste Feature-Ablation | AS-OPT-05; Intervall- und Verfügbarkeitsvertrag festlegen |
| Mehrere Beobachtungen und geglätteter GHI-Gain | P1, geeigneter Nowcast-Versuch | AS-OPT-06; eigene Berichtzeiten erhalten |
| Adaptiver Decay | P2, nach einfacher Glättung | Zweiter Kandidat in AS-OPT-06 |
| Wettermodellgewichte | P2, plausibel bei nachgewiesenen Modellunterschieden | AS-OPT-03 vor AS-OPT-07 |
| Automatische Modellauswahl und ICON-D2-Bevorzugung | P2, kein Auflösungsvorsprung ohne Standortmessung | Als getrennte Kandidaten in AS-OPT-07 |
| Ensemble-Spread | P2, zunächst Diagnose oder Feature | AS-OPT-09; keine automatische Wahrscheinlichkeitsaussage |
| Residual-Lags | P2, eher nach den ersten Feature-/Nowcast-Versuchen | AS-OPT-08; ausschließlich bei Ausgabe bekannte Residuen |
| Quantilregression | P2, eigene Unsicherheitsprüfung erforderlich | AS-OPT-09; getrennt von Punktprognosegewichten |
| Hyperparameter, feinere Regime, getrennte Leadmodelle | Zurückstellen | Erst bei ausreichenden unabhängigen Daten je Teilmodell; kein pauschales 60-Tage-Gate |
| Bewölkungs-/Temperaturtrends | Zurückstellen | In AS-OPT-06 erst nach einfacher Glättung und Nachweis zusätzlicher Information gegenüber Wetter/Physik |
| Mehr Origins je Bin | Nachrangig | Zuerst effektive Historienlänge und Origin-Gewichtung in AS-OPT-02/03 prüfen |
| Featurecache oder Archivkompression | Nur nach Ressourcenmessung | AS-OPT-02/04; Aggregation darf Zeit- und Featuresemantik nicht verlieren |
| 80-Prozent-Labels, 14-Tage-Light-Modus, bloße Ankerpersistenz | Derzeit nicht empfehlen | Keine Standardoptimierung; Qualitätsstatus ersetzt weder geeignete Labels noch beobachtete Kontinuität |
| Quorum als Ersatz der Kohortenregel | Derzeit nicht empfehlen | Erst Ausschlüsse messen; eine alternative Kohortenpolitik bräuchte einen eigenen vergleichbaren Referenzpfad |
| Deep Learning | Derzeit kein begründeter Vorrang | Datenunterstützung und gemessener Zusatznutzen fehlen als Entscheidungsgrundlage; eine GPU ist keine allgemeine Voraussetzung für jedes neuronale Modell |

## 3 Befunde mit Bedeutung für die Umsetzung

### 3.1 Refit und Trainingsjoin getrennt betrachten

`_history_revision` steigt auch beim Ergänzen noch laufender Messintervalle.
Die Signatur aus Revision und lokalem Datum kann deshalb bei jedem Fünf-Minuten-
Refresh einen Fit-Aufruf auslösen. `join_training()` läuft davor unabhängig von
dieser Prüfung. Ein Fit-Throttle spart daher nicht automatisch den Join. Die
Obergrenzen liegen bei 60.000 Forecastzeilen und 30.000 Istzeilen, nicht bei
insgesamt 30.000 Zeilen. Vor ausreichender Historie beendet der Lerner seine
Prüfung zudem ohne Baumtraining.

Ein Cache muss Änderungen der tatsächlich nutzbaren Trainingsdaten erkennen:
nicht nur deren Anzahl, sondern auch Inhalte, neu verfügbare Labels,
repräsentative Origins, Retention und die zeitliche Aufteilung. Ein verzögerter Fit
kann Aktivierung oder Ablehnung verschieben. Mess- und Beobachtungssperren müssen
unabhängig davon aktuell bleiben.

Belege: `_async_update_data`, `_append_interval`, `_archive_result` im
[Coordinator](../../custom_components/adaptive_solar/coordinator.py) sowie
`fit`/`_fit_regime` im [Lerner](../../custom_components/adaptive_solar/core/learning.py).

### 3.2 Einzelmodelle fehlen im Lernarchiv

`_archive_result()` speichert Ensemble-Baseline, Endprognose und Features. Die
lokal in der Engine bekannten Modellmitglieder, Einzelmodellleistungen und
Originalwetterzellen werden dort nicht mitgeschrieben. Aus einer gemittelten
Baseline lassen sich weder alternative Gewichte noch historische Spreads
rekonstruieren. Dafür braucht es zusätzliche prospektiv erfasste Eingaben oder
einen ausdrücklich als bedingt historisch bezeichneten Replaydatensatz.

`best_match` und `seamless` können dieselben zugrunde liegenden Modelle enthalten.
Die konfigurierten Kennungen sind deshalb keine unabhängigen Ensemblemitglieder.
Bekannte Providerkennungen archivieren; eine nicht gelieferte interne Modellwahl
oder NWP-Laufzeit nicht erfinden.
([Open-Meteo zur Modellauswahl](https://open-meteo.com/en/docs#best-match-model-selection))

### 3.3 Nowcast braucht zeitlich vergleichbare Referenzen

Der [Enginepfad](../../custom_components/adaptive_solar/core/engine.py) verlangt beim
Leistungsabgleich dieselbe gültige Modellkohorte wie für das Zielintervall. So
wird ein Unterschied zwischen Modellmischungen nicht als Anlagenfehler korrigiert.
Ein vollständig ausgefallenes Modell gehört dagegen bereits nicht zur gültigen
Ausgabekohorte. Die bloße Zahl konfigurierter Modelle erklärt die Ausfallhäufigkeit
des Nowcasts nicht.

Der HA-Adapter liest derzeit aktuelle Sensorzustände; es gibt keinen eigenen
Verlauf mehrerer vergangener Power-/GHI-Berichte für eine Glättung. Dafür sind
begrenzte Beobachtungspuffer und reproduzierbare Berichtarchive erforderlich.
Jede Beobachtung benötigt ihre eigene Momentanreferenz. Gleiche Modellkennung
allein genügt bei wechselnden Wetterständen nicht für einen unveränderten Gain.

Der GHI-Einfluss wird über ein 90-Minuten-Fenster integriert, der Leistungsrest
über bis zu drei Stunden. Eine teilweise überlappende Ausgabezelle kann ihren
gemittelten Einfluss bis zu ihrem Ende enthalten. Glättung und Decay müssen diese
Intervallverträge erhalten. Tests bestehen bereits für Sonnenbewegung,
Quellenlücken, GHI-/Power-Doppelkorrektur und ungleiche Lernunterstützung:
[Momentanreferenzen](../../tests/test_nowcast_reference.py),
[GHI](../../tests/test_irradiance.py), [Stufenkohorten](../../tests/test_physics_gaps.py).

### 3.4 Aktivierung und Unsicherheit bleiben getrennte Nachweise

Mindestens 28 Zieltage und 240 Stunden eindeutiger gemessener Dauer gelten **je
Stufe und Regime**. Zusätzliche Origins erzeugen keine neuen unabhängigen
Iststunden. Die interne Punktprognose muss strikt mehr als fünf Prozent
Leistungs-MAE gewinnen; mindestens 60 Prozent der Validierungstage müssen gewinnen.
Lead-Unterstützung und Kalibrierung haben weitere eigene Datenanforderungen.

Die aktuelle Fehlergrenze ist ein empirisches 90-Prozent-Quantil absoluter
Kalibrierungsfehler. Das ergibt keine nachgewiesenen bedingten P10/P90-Werte;
P10 bis P90 bezeichnet nominal ein 80-Prozent-Intervall. Auch direkte
Quantilregression braucht eine unabhängige Abdeckungsprüfung. Stundenquantile
lassen sich nicht ohne Prüfung ihrer zeitlichen Abhängigkeit zu Tagesquantilen
addieren. Der Code entfernt Unsicherheitsgrenzen bei angewandtem GHI-Pfad und
geänderter Power-Nowcast-Prognose weiterhin konservativ.
([Lerner](../../custom_components/adaptive_solar/core/learning.py),
[Quantilregression und Kalibrierung](https://scikit-learn.org/stable/auto_examples/ensemble/plot_gradient_boosting_quantile.html))

## 4 Vorschläge für Arbeitspakete

### AS-OPT-01 Messgrundlage und Vergleichsprotokoll

**Priorität P0 · Aufwand M · Voraussetzung:** keine anderen Optimierungspakete.

**Ziel und Ergebnis:** Ein eingefrorenes Protokoll bindet Quellstand, physische
Konfiguration einschließlich Dämpfung/Horizont, Messgrenze, Quellenqualifikation,
Ausgabezeiten, Datenverfügbarkeit und auszuwertende Horizonte. Bestehende
Capture-/Evaluationshelfer verwenden; fehlende Funktionen als konkrete Teilaufgaben
benennen. Private Zuordnungen und Rohdaten bleiben außerhalb Git.

**Abnahme:**

- Je Stufe sind anwendbare Mess-/Gültigkeits-/Abregelungsannahmen und die Ursachen fehlender Trainingsziele dokumentiert. Nicht konfigurierte optionale Signale sind von ungültigen konfigurierten Signalen getrennt.
- Auswahl-, interne Validierungs-, Kalibrierungs- und abschließende Prüftage sind zeitlich getrennt; spätere Labelverfügbarkeit wird nachgewiesen. Referenz und Kandidat erhalten dieselben verfügbaren Eingaben und Fit-Zeitregeln, sofern gerade diese nicht Gegenstand des Versuchs sind.
- Primärmetrik, Prüfperiode, Strata, Mindestabdeckung, Umgang mit Fallbacks/Ausfällen sowie Annahme- und Abbruchkriterien stehen vor Ergebnissichtung fest.
- Ausgabe ist ein reproduzierbares Vergleichsprotokoll mit Bereitschaftsstatus. Fehlende Daten führen zu einem begründeten Sammelbedarf, nicht zu einem bestandenen Gütegate.

**Betroffene Stellen:** [Validierungsplan](../entwicklung/validierung.md),
[Aufnahmeleitfaden](../entwicklung/benchmark-aufnahme.md), `scripts/capture_ha.py`,
`scripts/capture_actuals.py`, `scripts/evaluate.py`, `core/evaluation.py`.

### AS-OPT-02 Ressourcen und vorhandene Diagnosen auswerten

**Priorität P0 · Aufwand M · Voraussetzung:** für lokale synthetische Messungen keine;
für reale Interpretation AS-OPT-01.

**Ziel und Ergebnis:** Ein reproduzierbarer Bericht trennt Join, Fit-Prüfung,
tatsächliches Baumtraining, Physik/Nowcast und Archivpflege. Vorhandene
`training_quality`- und Modellstatusdaten nutzen; fehlende Aggregationen oder
Zeitmessungen gezielt ergänzen.

**Abnahme:**

- Kalter und aktivierter Lerner, unterschiedliche Stufenzahlen und Historiengrößen bis zu den Zeilenlimits sind mit Umgebung, Wiederholungszahl, Median/p95 der Laufzeiten und Speichermaß beschrieben.
- Refit-Auslöser durch Isthistorie, Tageswechsel und Änderungen der serialisierten Schattentabelle sind getrennt erfasst, einschließlich neuer Aufnahmen bei unverändertem freigegebenem Median.
- Akzeptierte eindeutige Trainingsstunden, effektive Historienlänge und Nowcast-Ausschlüsse werden je Stufe/Horizont ausgewiesen. Der Nenner für Nowcast-Quoten umfasst geeignete Tageslichtziele; Gründe dürfen überlappen und werden nicht als disjunkte Fallzahlen addiert.
- Ungültige Messquelle, schwache Strahlung, unvollständige GHI-Kohorte, fehlende Momentanabdeckung und nicht vergleichbare Lernunterstützung bleiben unterscheidbar.
- Eine begründete Entscheidung nennt den tatsächlichen Engpass oder verwirft eine Performanceänderung. Ein zulässiges Aktualitätsbudget wird vor AS-OPT-04 festgelegt. Diagnoseänderungen lassen Prognosewerte unverändert.

**Betroffene Stellen:** `coordinator.py`, `diagnostics.py`, `sensor.py`,
`core/engine.py`, `core/learning.py` und ein lokaler Messhelfer.

### AS-OPT-03 Einzelmodelle und Vergleichseingaben archivieren

**Priorität P1 · Aufwand L · Voraussetzung:** AS-OPT-01 für Zeit-/Provenienzvertrag;
Ressourcenbudget aus AS-OPT-02.

**Ziel und Ergebnis:** Ein versioniertes Archiv hält je Ausgabe, Stufe und
Zielintervall die gültigen Modellmitglieder, Einzelmodellleistungen an derselben
AC-/DC-Grenze und die Aggregationspolitik fest. Originalwetter oder unveränderliche
Referenzen darauf erlauben die Wiederholung mit den damals verfügbaren Eingaben.
NWP-Ausgang, GHI-Anwendung und endgültige Lern-/Powerkorrektur bleiben zuordenbar.

Die [Vertiefung zu Physikvergleich und Archivierung](physikvergleich-und-archivierung.md)
konkretisiert den Vorschlag mit Datenvertrag, HA-Exportpuffer, externem
Langzeitarchiv und Abnahmekriterien. Der Entwicklungsstand vom 28.10.2026 enthält
Export, Archiv und Replay; [Betrieb und Grenzen](../archiv/archivbetrieb.md) bleiben von
Pilotbetrieb und gemessener Prognosegüte getrennt.

**Abnahme:**

- Ausgabe-/Empfangszeiten, Originalintervall, Modellkennung, Kohorte, Features und Konfigurations-/Vertragsbindung sind ausreichend, um den aktuellen Mittelwert samt nachfolgenden Stufen zu reproduzieren. Fehlende Mitglieder bleiben fehlend.
- Export, Roundtrip und Wiederholung erhalten Resultate sowie eindeutige Messdauer; zusätzliche Origins vervielfachen keine Labels.
- Ablage und Retention sind entschieden: zusätzliche Vergleichsarchive verkürzen nicht unbemerkt die Lernhistorie oder blähen den HA-Store unbegrenzt auf. Private Rohdaten werden nicht veröffentlicht.
- Alte Ensemblezeilen bleiben als solche lesbar. Fehlende Einzelmodelle werden nicht rückwirkend erfunden. Reine Zusatzmetadaten und Änderungen von Lernfeatures erhalten getrennte Schema-/Migrationsregeln.

**Betroffene Stellen:** `weather.py`, `core/engine.py`, `core/models.py`,
`coordinator.py` sowie Export-/Replayhelfer und Archivtests.

### AS-OPT-04 Refit und Join gezielt begrenzen

**Priorität P1 · Aufwand M · Voraussetzung:** AS-OPT-02 weist relevanten Aufwand aus.

**Ziel und Ergebnis:** Ein Kandidat vermeidet unnötige Rekonstruktionen, ohne
Messsperren zu verzögern. Zunächst inhaltsbezogene Invalidierung beziehungsweise
Caching prüfen; einen festen Refit-Abstand als getrennte Politik bewerten.

**Abnahme:**

- Unveränderte effektive Trainingsdaten ergeben gegenüber der Referenz gleiche Prognosen, Aktivierungszustände und Bounds. Änderungen mit gleicher Zeilenzahl invalidieren den Cache korrekt.
- Neue verfügbare Labels, geänderte Origins, Retention, Tages-/DST-Wechsel sowie Neustart und Vertrags-/Konfigurationswechsel werden korrekt berücksichtigt.
- Gültigkeits- und Abregelungswechsel sperren betroffene neue Beobachtungen sofort, unabhängig vom letzten Fit. Bewusst verzögerte Modellentscheidungen bleiben innerhalb des vorher festgelegten Aktualitätsbudgets und sind diagnostizierbar.
- Join und Fit werden erneut separat gemessen. Nur ein belegter Ressourcen-/Aktualitätsvorteil rechtfertigt die Änderung; bei aktiver Verzögerung wird die gesamte Forecastpolitik verglichen.

**Betroffene Stellen:** `coordinator.py`, gegebenenfalls `core/learning.py`;
Regressionen zu Persistenz, Alignment, Messgültigkeit und Regimetrennung.

### AS-OPT-05 Clearness Index als einzelnes neues Feature

**Priorität P1 · Aufwand M · Voraussetzung:** AS-OPT-01. Implementierung und
prospektive Featureerfassung können der Güteauswertung vorausgehen; diese braucht
ausreichend passende Featurehistorie. Das vollständige Einzelmodellarchiv aus AS-OPT-03 ist keine harte
Voraussetzung; die benötigten Strahlungsinputs müssen dennoch archiviert werden.

**Ziel und Ergebnis:** Ein Kandidat ergänzt genau ein definiertes Wetterfeature.
Als erste Definition bietet sich je Mitglied ursprüngliche NWP-GHI geteilt durch
die Clear-Sky-GHI über dasselbe Originalintervall an, anschließend nach der
gültigen Kohorte aggregiert. Gemessene Momentan-GHI wird nicht als zukünftiges
Stundenmittel eingesetzt. Der zusätzliche Nutzen gegenüber Baseline, Bewölkung
und bestehendem GHI-Gain ist experimentell zu prüfen.

**Abnahme:**

- Formel, Quellintervall, Aggregation und Verhalten bei Nacht, Schwachlicht und ungültigen Werten sind festgelegt und verhalten sich bei Teilzellen sowie beiden DST-Wechseln korrekt.
- Das Feature ist bei Ausgabe verfügbar und wird prospektiv gespeichert. Vertragswechsel verwirft unverifizierbare alte Features, erhält separat kompatible Messdaten und ausgegebene Tagesbeginn-Snapshots.
- Ein Vergleich mit/ohne Feature hält Physik, übrige Features, Hyperparameter und Messgates gleich. Ergebnisse liegen je Stufe, Regime und Horizon vor; unzureichende Historie bleibt Physikfallback.

**Betroffene Stellen:** `core/engine.py`, `core/physics.py`, `core/learning.py`,
`coordinator.py`; Feature-, Regime- und Persistenztests.

### AS-OPT-06 Beobachtungsverlauf und Nowcast Glättung

**Priorität P1 · Aufwand L · Voraussetzung:** AS-OPT-01 und Ausschlussdiagnose aus
AS-OPT-02. Erfassung und begrenzte Puffer sind ein erster Teilschritt; die
Güteauswertung setzt ausreichend echte Beobachtungsverläufe voraus.

**Ziel und Ergebnis:** Begrenzte Puffer halten ursprüngliche Power-/GHI-Berichte
mit ihren Zeiten und gültigen Phasen. Zunächst zeitlich normalisierte
Residual-/Gain-Glättung gegen den unveränderten Nowcast prüfen. Power und GHI sind
getrennte Ablationen. Adaptiver Decay und Trends folgen als weitere einzelne
Kandidaten, sobald die einfache Glättung bewertet ist.

**Abnahme:**

- Jeder gespeicherte Bericht behält Quelle, Zeitpunkt, Qualitätsphase und passende Wetter-/Lernreferenz. Lücken, Wiederanlauf und neue Wetterstände übernehmen keinen unpassenden alten Gain; es werden keine frischen Messzeitpunkte aus Mittelwerten erzeugt.
- Abregelung, Messungültigkeit, GHI-/Power-Zeitreihenfolge, Kohorten und Lernunterstützung bleiben erhalten. Ein Verlauf wird nicht durch ungeprüfte zusätzliche HA-Zählerpolls erzeugt.
- Der Vergleich umfasst Sonnenbewegung ohne Wetterfehler, stabile Fehler, Wolkenwechsel/Verzögerung, Ausfälle und Ausgangsclip. Mehrfachkorrektur desselben GHI-/Powerfehlers ist ausgeschlossen.
- Kurzfristige Leistungs- und Restenergiefehler sowie Reaktionsverzug werden auf identischen Aufgaben verglichen. Eine kurzfristige Verbesserung gilt nicht automatisch für Day-ahead; Unsicherheitsbänder bleiben ohne eigene Kalibrierung unbehauptet.

**Betroffene Stellen:** Beobachtungserfassung im `coordinator.py`,
`core/engine.py`, Beobachtungsarchiv und vorhandene Nowcast-/Quellenqualitätstests.

### AS-OPT-07 Gewichte und Auswahl der Wettermodelle

**Priorität P2 · Aufwand L · Voraussetzung:** AS-OPT-01 und AS-OPT-03 mit
ausreichenden gepaarten Einzelmodelldaten.

**Ziel und Ergebnis:** Zunächst wenige nichtnegative, auf Summe eins normierte
und zur Gleichgewichtung regularisierte Gewichte prüfen. Auswahl der Mitglieder,
Horizontabhängigkeit und feste ICON-D2-Bevorzugung sind weitere getrennte
Politiken. Kosten und Abdeckung zählen neben dem Forecastfehler.

Die [Wettermodellrecherche vom 28.10.2026](wettermodelle-und-prognosehorizonte.md)
konkretisiert den Archivgrundbestand, die Priorität der ersten 24/48 Stunden und
den Wechsel bei auslaufenden Regionalmodellen. Sie dokumentiert außerdem die
Begrenzung durch kalendertagsbezogene Abrufe; eine lokale Genauigkeitsrangliste
oder implementierte Bevorzugung folgt daraus nicht.

**Abnahme:**

- Gewichte werden ausschließlich aus vor Ausgabe verfügbaren älteren Daten bestimmt; die abschließenden Prüftage bleiben von Auswahl und Tuning unberührt. Modellüberlappungen und unterschiedliche Horizonte sind ausgewiesen.
- Physik je Mitglied und gemeinsamer Stufenclip werden nicht durch ein unbeabsichtigtes Mitteln der Wetterinputs ersetzt. Fehlende Arme verändern die Gewichte nach einer festgelegten, reproduzierbaren Regel.
- Dieselbe fachliche Gewichtungs-/Kohortenpolitik gilt für Ziel und passende Momentanreferenz. Änderungen von Baseline und Features sind versioniert; alte Residualmodelle werden nicht unbesehen weiterverwendet.
- Der Kandidat schlägt den aktuellen gleichgewichteten Gesamtpfad nach dem eingefrorenen Protokoll. Gewinne an einzelnen Anlagen verdecken keine unzulässigen Verluste anderer Anlagen oder Horizonte.

**Betroffene Stellen:** `core/engine.py`, Archiv-/Gewichtsmodell,
`core/learning.py` und chronologischer Replay-/Evaluationspfad.

### AS-OPT-08 Residual Lags unter strikter Verfügbarkeit

**Priorität P2 · Aufwand M bis L · Voraussetzung:** AS-OPT-01 und ein Archiv
verfügbarer abgeschlossener Residuen. Das Ergebnis von AS-OPT-05/06 hilft bei der
Priorisierung, ist keine technische Voraussetzung.

**Ziel und Ergebnis:** Ein kleiner vorab definierter Satz vergangener Residuen
wird gegen den bereits vorhandenen Lern-/Nowcastpfad geprüft. Beispielsweise darf
ein Morgenforecast kein Residuum aus einer erst später gemessenen Stunde desselben
Zieltags erhalten. Zeitlicher Split allein verhindert diesen Fehler nicht.
([Zeitreihenfeatures und Bewertung](https://scikit-learn.org/stable/auto_examples/applications/plot_time_series_lagged_features.html))

**Abnahme:**

- Für jeden Lag sind Referenzausgabe, Messende, tatsächliche Verfügbarkeit und passende Baseline-/Konfigurationsbindung bekannt. Verzögert eingegangene Labels bleiben vor Empfang unzugänglich.
- Fehlende Lags und Qualitätswechsel haben einen expliziten Fallback. Neue Features erhalten einen eigenen Vertrag und werden nicht aus später vervollständigter Historie rückdatiert.
- Vergleich mit/ohne Lags hält den Nowcast gleich und weist zusätzlichen Nutzen je Horizont aus; reine Duplizierung der schon vorhandenen kurzfristigen Korrektur rechtfertigt keine Übernahme.

**Betroffene Stellen:** `coordinator.py`, `core/learning.py`, Featurearchiv und
Tests zu as-of-Verfügbarkeit, Wiederanlauf und verzögerten Labels.

### AS-OPT-09 Unsicherheit getrennt kalibrieren

**Priorität P2 · Aufwand L · Voraussetzung:** AS-OPT-01; für Ensemble-Spread
zusätzlich AS-OPT-03. Quantilregression benötigt das Einzelmodellarchiv nicht
zwingend, wohl aber passende Feature-/Kalibrierungsdaten.

**Ziel und Ergebnis:** Zuerst Spread als Modellunterschied messen. Anschließend
einen eigenen Kandidaten für kalibrierte Intervalle oder Quantilregression
definieren; diese beiden Stufen lassen sich in getrennte Tickets aufteilen.

**Abnahme:**

- Nominale Abdeckung, Punktprognose, Leistungs-/Energiegröße und auszuwertende Horizonte sind eindeutig festgelegt. Aktuelle 90-Prozent-Absolutfehlerbänder werden nicht als P10/P90 umbenannt.
- Unabhängige Prüfdaten belegen Coverage und Intervallbreite je Stufe/Horizont; Quantilmodelle werden zusätzlich mit Pinball-Loss bewertet. Auswahl- und Kalibrierungsdaten ersetzen diese Prüfung nicht.
- Nicht kreuzende Grenzen, Nacht und physische Clips werden an den tatsächlich veröffentlichten Werten geprüft. Tagesintervalle brauchen einen eigenen Aggregations-/Abhängigkeitsnachweis.
- Unkalibrierte GHI-/Power-Nowcast-Korrekturen übernehmen keine ML- oder Spread-Bounds. Die Rückfallebene bleibt ohne erfundene Unsicherheit nutzbar.

**Betroffene Stellen:** `core/learning.py`, `core/engine.py`,
`core/evaluation.py`, Sensorausgabe und Kalibrierungs-/Coverageauswertung.

## 5 Reihenfolge und gemeinsame Abnahme

1. **AS-OPT-01 und AS-OPT-02 zuerst:** Messbereitschaft und tatsächliche Engpässe klären. Quellenprobleme werden an ihrer Ursache behandelt, nicht durch gelockerte Trainingsgates.
2. **AS-OPT-03 früh vorbereiten:** Die nötige Datensammlung hat Vorlauf. Ein Archiv lässt sich vor einer Entscheidung über Gewichte beginnen; sein Betrieb ist ein eigener beauftragbarer Schritt.
3. **AS-OPT-04 nur nach Kostenbefund:** Ohne relevanten Engpass ist auch das begründete Zurückstellen ein abgeschlossenes Untersuchungsergebnis.
4. **AS-OPT-05 und AS-OPT-06 einzeln vergleichen:** Erst isolierte Effekte, danach gegebenenfalls eine Kombination prüfen. Aktive Morgen-/Abenddämpfung und Horizonte bleiben dabei eingefroren.
5. **AS-OPT-07 bis AS-OPT-09 nach Datennachweis:** Gewichte, Lags und Intervalle sind unabhängige Fragestellungen, keine zwangsläufige gemeinsame Modellablösung.

Für jedes Ticket werden vor Beginn Ausgangshash, konkrete Eingaben, Ergebnisdateien,
Abhängigkeiten, Abnahmekriterien und die noch festzulegenden Versuchsparameter
übernommen. Zahlen für Pufferlänge, Refitabstand oder Gewichte werden anhand des
jeweiligen Vorpakets gewählt und vor der abschließenden Auswertung eingefroren.
Fehlende Datengrundlage, kein Zusatznutzen oder eine Verschlechterung sind zulässige
Untersuchungsergebnisse; sie begründen keine Aktivierung.

**Drei Abnahmen bleiben getrennt:**

- **Implementierung:** sinnvolle Verhaltenstests, passende native HA-Prüfungen und Prüfung der Zeit-/Messverträge; beide DST-Wechsel, Lücken, Neustart und Qualitätswechsel dort abdecken, wo der jeweilige Pfad betroffen ist. Reine Dokumentationsänderungen benötigen keine vollständige HA-Testmatrix.
- **Kandidatenentscheidung:** Vergleich gegen die eingefrorene aktuelle Gesamtpolitik auf identischen Aufgaben; vorab festgelegte Energie-/Leistungsmetriken, Bias-, Abdeckungs- und Aktualitätsgrenzen je Stufe/Horizont. Die interne Learner-Aktivierung bleibt ein separates Gate.
- **Externer Gütenachweis:** unverändert nach [Validierungsplan](../entwicklung/validierung.md): mindestens 30 vollständige gepaarte Zieltage je Stratum, mindestens fünf Prozent niedrigere Energie-MAE gegen beide Referenzen, mindestens 60 Prozent gewonnene Tage, kein größerer absoluter Energie-Bias und keine Verschlechterung über zwei Prozent an einer Stufe. Falls statistische Annahme beansprucht wird, gilt die dort definierte gemeinsame Tages-Bootstrap-Policy mit ihren Annahmen und Grenzen.

Externer Review, Veröffentlichung und produktive Installation folgen den
[bestehenden Verfahren](../entwicklung/entwicklung.md#3-veröffentlichung-und-nachweise).
Implementierung, unabhängiger Review, Installation und reale Güte werden nicht
zu einer einzigen Abnahme zusammengezogen. Ein Archiv- oder Versuchsplan ändert
keine produktiven HA-Einstellungen.

## 6 Quellen und Prüfumfang

Die Befunde beruhen auf dem oben gebundenen Repositorystand, dem Vergleich mit
`0285445`, den verlinkten Implementierungen und vorhandenen Verhaltenstests.
Für diese Bewertung wurde kein neuer Modellkandidat trainiert, kein HA-Livezustand
abgefragt und keine neue Gütemessung durchgeführt. Frühere Testzahlen und
Reviewreceipts werden nicht auf dieses Dokument übertragen.

Ergänzende Primärquellen, abgerufen am 26.10.2026:

- [Open-Meteo Forecast API](https://open-meteo.com/en/docs): Modellkombinationen und Strahlungsintervalle, keine lokale Rangliste der PV-Prognosegüte.
- [scikit-learn zu Lag-Features](https://scikit-learn.org/stable/auto_examples/applications/plot_time_series_lagged_features.html): zeitlich geeignete Bewertung und Featureverfügbarkeit.
- [scikit-learn zu Quantilintervallen](https://scikit-learn.org/stable/auto_examples/ensemble/plot_gradient_boosting_quantile.html): getrennte Prüfung der Intervallabdeckung.

Nachweise werden anhand des geprüften Commits gelesen, da sich Funktionspositionen
und öffentliche Anbieterbeschreibungen ändern können. Die Untersuchungspakete
enthalten weder private Standorte noch konkrete Messbindungen oder Zugangsdaten.
