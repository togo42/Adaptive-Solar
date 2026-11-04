# Korrekturen der unabhängig geprüften Grok-Befunde

Historischer lokaler Korrektur- und Prüfstand vor dem getrennten Hostwechsel
und der Releasevorbereitung 0.2.22. Spätere Veröffentlichungs- und
Installationsnachweise stehen in den [Releasehinweisen](../releases/release-0.2.22.md).

Stand: 03.11.2026, Entwicklung nach `cd36f95`. Grundlage ist die
[Prüfung aller 41 Meldungen](grok-befundpruefung-20261103.md) gegen `4a74f4b`.
Diese Seite beschreibt die anschließenden Korrekturen der neun bestätigten und
14 teilweise bestätigten Themen. Die ursprünglichen Urteile bleiben als
historischer Prüfstand erhalten. Drei Subagenten bearbeiten Qualität/Zeit,
Physik/Schatten und HA/Persistenz; ein anderer Bearbeiter prüft jede Familie
einschließlich ihrer Aufrufer nach.

Die Änderungen sind ein Entwicklungsstand nach dem veröffentlichten 0.2.21.
Sie sind keine neue Veröffentlichung oder produktive Installation. Geänderte
Integrationsquellen ändern den Producerhash; historische Pins bleiben an ihre
Originalquellen gebunden. Neue Quellenbindungen brauchen für einen späteren
Runtimewechsel neue prospektive Belege.

## Vollständige Zuordnung der offenen Themen

| Thema | Korrektur und beibehaltene Grenze | Regression oder Primärbeleg |
| --- | --- | --- |
| Q1 | Empfangs-, Quellen-, Bindungs- und Zielbereichsfilter greifen vor semantischer Intervallprüfung. Relevante ungültige Intervalle bleiben Fehler. Vollinputhash und Originalintegrität bleiben erhalten. | [Qualitätsregressionen](../../tests/test_quality_audit_regressions.py) |
| Q2 | Ein belegter Konfigurations-/Producer-/Generationswiderspruch publiziert eine kompakte negative Bereichsmaske über alle vollständig vergangenen UTC-Stunden der Bindung, auch außerhalb des aktuellen Capturefensters. As-of- und tatsächliche Validierungszeiten bleiben wirksam. | [Disjunkte Captures und fortlaufender Pfad](../../tests/test_quality_audit_regressions.py), [Vertrag](../archiv/istwert-qualitaetsadapter.md) |
| Q4 | `TrainingSample` prüft bereits am Konstruktor Ausgabe vor/bei Zielbeginn und Beobachtung ab Zielende. Join/Fit behalten ihre zusätzlichen Gates. | [Modelltests](../../tests/test_models.py), [Lerntests](../../tests/test_learning.py) |
| Q5 | Originalintegration verwirft ungültige Baselines, einschließlich Boolean, nichtendlichen und übergroßen Werten; unterstützte Fenster werden nicht umgedeutet. | [Originalintegration und Endpunktjoin](../../tests/test_measurement_lineage.py) |
| P2 | Export friert den tatsächlich überwachten Beginn der Messgültigkeitsphase ein. Replay prüft Phase, Rohzustand und Leistung gemeinsam; alte Aufnahmen ohne Beleg qualifizieren keine solche Leistung für Schattenneulernen. | [Nativer Capture und Replay](../../tests/test_shade_replay.py), [Phasenvertrag](../technik/measurement-validity.md) |
| P3 | Frische klare Leistung wird durch veraltete ungültige Beobachtungen nicht mehr gesperrt; gleichzeitige/spätere gültige Sperrbelege bleiben wirksam. Die Capprüfung gilt auch bei falsch gesetztem Eingabeflag. | [Schattenlerntests](../../tests/test_shade_learning.py) |
| P4 | Früher Bias-Shadow prüft die gesamte Spannweite der Schattenfaktoren zusätzlich zur Ankerkompatibilität. | [Extremfall und zulässige Familie](../../tests/test_early_bias.py), [Vertrag](../technik/early-bias-shadow.md) |
| P6 | Ein fehlender Stufenschlüssel in der Phasenabbildung entfernt dessen flüchtigen Nowcastverlauf. | [Verlaufsregressionen](../../tests/test_nowcast_history.py) |
| P7 | Synthetische Wetterzellen reichen mit verkürzter letzter Zelle bis zum lokalen Horizontende, auch bei gebrochenen UTC-Offsets. Erstes Demomodell und Mittelpunktnäherung sind ausdrücklich erklärt. | [CLI-Zeitzonentests](../../tests/test_cli.py), [Demo](../../README.md) |
| H1 | Fehlgeschlagenes Setup widerruft eine teilfertige Schreibfreigabe vor Cleanup-Awaits, entlädt weitergeleitete Plattformen und bereinigt Coordinator, Messlistener, Optionslistener und Dienstbesitz unabhängig. Retry erzeugt eine aktive Instanz. Native Registry-/Restore-Platzhalter bleiben erhalten. | [Native Fehler- und Retrypfade](../../tests/test_setup_rollback.py) |
| H3 | Leere/ungültige Modellwahl erhält einen eigenen Formularfehler. Direkte Handler validieren numerische Werte vor Änderung des Entwurfs; native Schemaprüfung bleibt erhalten. | [Config-/Optionsflows](../../tests/test_config_flow.py), übersetzte Fehlertexte |
| H4 | Import und Laden prüfen Tagessumme und jede Kurvenzelle gegen die ursprüngliche physische Cap, mit ausschließlich `1e-12`-Rundungstoleranz. Unlesbare Pflichtdaten bleiben gesichert und schreibgeschützt. | [AC/DC und 23/24/25 Stunden](../../tests/test_snapshot_caps.py), [Importvertrag](../technik/forecast-repairs.md) |
| H5 | Familienmischung und anschließende Biaskorrektur behalten Unvollständigkeitsstatus und produktqualifizierte Ausschlussnamen. Familiengewichte bleiben unabhängig von der Mitgliederzahl. | [Wahrscheinlichkeitsregressionen](../../tests/test_probabilistic_forecasts.py) |
| H6 | `capture_complete` bezeichnet den dauerhaften Transfer; `ensemble_cohort_complete` und Coverage-`cohort_complete` benennen getrennt die Mitgliedsvollständigkeit. Altes `complete`/Exit 0 bleibt die Transferaussage; Replay prüft weiter Quorum 1,0 als Standard. | [Echter Collector-/Host-CLI-Pfad mit Teilensemble](../../tests/test_weather_capture_status.py) |
| H7 | EPS-Replay lehnt gemischte AC/DC-Standorte vor der Mitgliedsberechnung ab und benennt die homogene Messgrenze, Stufen und Summenbildung im Bericht. Ist-/Kalibrierungsbelege müssen genau diese Summe betreffen. | [AC/DC-Replay und gemischter Fehlerfall](../../tests/test_archive_replay.py) |
| R5 | `--comparison-archive` verlangt explizite `input.sources`; fehlende Auswahl führt vor der Berichtveröffentlichung zu einer verständlichen Fehlermeldung. Bewusste Teilfamilien werden nicht automatisch erweitert. | [CLI und Originalerhalt](../../tests/test_comparison_archive.py), [Vergleichsvertrag](../technik/model-comparison-archive.md) |
| R6 | HA-, Wetter- und kompatible Observations-Timervorlagen verwenden UTC wie bereits Actuals/References. Lokale tägliche Retention bleibt lokal. Installierte Timer benötigen einen getrennten Runtimewechsel. | [Zwölf native Kalenderfälle](../../tests/test_archive_timer_calendars.py), [Hostanleitung](../archiv/archiv-host-installation.md) |
| D1 | Bedienung und Messvertrag erklären Innenlückenbudgets zusätzlich zu weiterhin gültigen 92 % Abdeckung und 180 Sekunden je Rand. Alte Daten ohne Phasenbeleg müssen zusammenhängen. | [Bedienung](../anwendung/bedienung.md), [Messvertrag](../technik/measurement-learning.md) |
| D4 | Datenschutz nennt den separaten Ensemble-Endpunkt samt übertragenen Koordinaten und die seit 0.2.21 veröffentlichten Profile. | [Datenflüsse](../anwendung/datenschutz.md) |
| D5 | Installationsanleitung nennt 0.2.21 und erklärt HA-/Hostupgrade, Streamtrennung, Erhalt von Originalen/Pins sowie neue Producerbindung. | [Upgrade](../anwendung/installation.md) |
| D6 | Bedienungskopf und Releaselink verweisen auf den beschriebenen veröffentlichten Funktionsumfang 0.2.21. | [Bedienung](../anwendung/bedienung.md) |
| D7 | Archivbetriebsanleitung nennt 0.2.21; fortlaufende Qualitätsaufnahme wird als verfügbar beschrieben, ihre Timeraktivierung bleibt eine gesonderte Entscheidung. Nachfolgende Entwicklungskorrekturen sind gekennzeichnet. | [Archivbetrieb](../archiv/archivbetrieb.md) |
| D8 | Einheitenwechselregel wird dem veröffentlichten 0.2.20 statt einem unveröffentlichten Kandidaten zugeordnet. | [Messvertrag](../technik/measurement-learning.md) |

P1 erhält zusätzlich die im Audit empfohlene Kommentarpräzisierung zur optionalen
Momentanbeobachtung; die Fail-closed-Regel der Teilintegration bleibt unverändert.
Die widerlegten Themen Q3, P1, P5, H2, R1, R4, R7, D3 und D9 benötigen keine
behauptete funktionale Fehlerkorrektur. Die bereits behobenen R2, R3 und D2
bleiben erhalten und werden durch die bestehenden Regressionen abgedeckt.

## Validierung und Nachweisgrenzen

Der eingefrorene integrierte Stand besteht unter Python 3.14 und echtem
HA Core 2026.10.4 **3.077 Tests ohne Skips** bei **91,45 % kombinierter
Zeilen-/Zweigabdeckung**. Das bestehende 90-%-Gate bleibt unverändert.
Die Vollsuite verwendet das echte Rustmodul auch für reguläre Ableitung und
den neuen periodenweiten Konfliktfall. Zusätzlich bestehen **42 historische
Native-Differential-/Projektionsfälle**. Ruff, `pip check`, Whitespaceprüfung,
relative Dokumentationslinks und die vollständige 23-Themen-Zuordnung sind
geprüft. Die Quell-/Test-/Unitdateien blieben seit Beginn dieses finalen Laufs
bytegleich; ein früherer Lauf während der noch laufenden Pin-/Fixturekorrekturen
ist ausdrücklich kein Abnahmenachweis.

Alle Familien wurden durch einen anderen Bearbeiter nachgeprüft; anschließend
wurde der vollständige integrierte Diff einschließlich neuer Tests und
Dokumentation nochmals unabhängig gelesen. Dabei gefundene Randfälle bei
übergroßen Integern sowie die alte Tagesenergie-Toleranzangabe wurden korrigiert.
Es bleiben in diesem abgegrenzten Befundumfang keine offenen Punkte.

Die Korrekturen erhalten gezielte Verhaltensregressionen einschließlich echter
HA-Plattformen, Dienste, Dateipersistenz, Retry, eingefrorenem Export und
Subprozess-Replay. Die Kalenderfälle werten die ausgelieferten Vorlagen lokal
mit `systemd-analyze` aus; sie starten keine Dienste. Der reale Rustkern wird
zusätzlich gegen den aktuellen Pythonpfad geprüft.

Ein bestandener Test oder lokaler Nachreview ist kein neuer externer
Grok-Vollreview und kein Beleg physischer Quellenqualität oder besserer
Prognosen. Produktionszustände wurden für diese Korrekturen nicht verändert.
