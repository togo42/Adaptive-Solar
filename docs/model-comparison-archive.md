# Prospektives Vergleichsarchiv der Modellarme

Stand: 27.10.2026; lokale Implementierung nach 0.2.14. Dieses Archiv schafft
prüfbare Originalausgaben für einen späteren Vergleich. Es verändert weder die
operative Prognose noch Trainingsdaten, Modellgewichte oder Annahmekriterien.
Ein vorhandenes Archiv oder ein Review belegt keine bessere Prognose.

## Quellen und Bindung

Der getrennte feste private HA-Store
`adaptive_solar.<entry_id>.comparison_v1` speichert eigenständige Captures
folgender Quellen. Er hat HA-Store-Version 1/minor 1; `data` enthält den
Vergleichsvertrag mit `schema_version=1` direkt. Der normale Mess-/Lernstore
`history_v2` enthält dieses Archiv nicht:

| Quelle | Bedeutung |
| --- | --- |
| `adaptive` | Tatsächlich ausgegebene operative Leistung einschließlich freigegebener Korrekturen |
| `operative_baseline` | Zugehörige Baseline vor Residual-/Leistungs-Nowcast; kann aktuelle GHI- und Schattenkorrektur enthalten |
| `shadow:early_bias` | Ausschließlich separat berechneter Bias-Kandidat; seine Ausgaben gelangen nicht in operative Prognose oder ML-Archiv |
| `nwp:<model>` | Originale reine NWP-Physik des jeweiligen verfügbaren Wettermodells, ohne lokale Beobachtungs-, Schatten-, Residual- oder Nowcastkorrektur |

`operative_baseline` ist die direkte Kandidatenreferenz und keine als reine
NWP-Physik umbenannte Prognose. Einzelne NWP-Arme sind getrennte Referenzen.
Gemeinsamkeit von Wetterdaten oder Physik bedeutet keine statistische
Unabhängigkeit. Die Anlage, ihre physischen Messgrenzen, die ursprünglichen
Ausgangskappen und ihre Zeitzone sind durch Konfigurations-/Historyhash und
Metadaten gebunden. Eine inkompatible Konfiguration beginnt diesen optionalen
Vergleichszweig neu. Dieses Archiv speist niemals `join_training`.

Je Capture bleiben der ursprüngliche Berechnungszeitpunkt `calculated_at`, die
**tatsächliche lokale Archivverfügbarkeit** `retrieved_at`, die ursprünglichen
Wetterausgaben `weather_issued_at` und der Quellstatus erhalten. Älteres Wetter
erhält keinen neuen Wetterausgabezeitpunkt. Die für Evaluation verwendete
Ausgabezeit ist immer `retrieved_at`; ein späterer lokaler Empfang wird niemals
auf den ursprünglichen Wetterissue zurückdatiert.

Archiviert werden nur noch zukünftige Zielteile. Ein laufendes Prognoseintervall
beginnt frühestens an der tatsächlichen Archivverfügbarkeit; `original_start`
erhält seine ursprüngliche Grenze. Das ursprüngliche prognostizierte
Intervallmittel bleibt erhalten. Das Zuschneiden einer Prognose ist keine
Messdelta-Aufteilung und liefert keine neu gemessene Feinauflösung.

## Feste Capturepolitik und brauchbare Aufbewahrung

Je Arm und **lokalem Anlagentag** zählt genau der erste echte
Prognoseversuch mit Archivempfang **ab 18:00 Uhr**, einschließlich eines
beobachteten Wetter- oder Physikausfalls. Läuft er beispielsweise erst um
18:07:12, bleibt dies seine Verfügbarkeitszeit. Es gibt keine stündlichen
Vollkurven, kein Zurückdatieren auf 18:00 und keine Auswahl nach Prognosefehlern.
Vorherige Tagesläufe ersetzen diesen Capture nicht. Ein als `unavailable`
archivierter Fehlversuch bleibt der Tagescapture; ein späterer Erfolg desselben
Tages ersetzt ihn nicht. Gibt es am verbleibenden Abend keinen beobachteten
Versuch, entsteht für diesen Tag eine Archivlücke. Beide Zeitumstellungen verwenden die
konfigurierte Zeitzone; Zielintervalle und Dauern bleiben UTC-bezogen.

Grenzen gelten gleichzeitig für das gesamte Vergleichsarchiv: **höchstens
120 Tage**, **250.000 Punktzeilen** und **1.024 ganze Quellcaptures**. Bei Platzmangel
entfallen die ältesten ganzen Captures, niemals nur ungünstige Punkte einer Kurve.
Hashes und Kappen stehen einmal am Archiv. Punktzeilen werden als kompakte Arrays
mit einmal deklarierten `point_columns` gespeichert; keine redundanten
Konfigurationshashes pro Punkt.

Eine Beispielanlage mit vier Ausgangsstufen, sieben Tagen stündlicher Prognose
und sechs Armen erzeugt `4 × 7 × 24 × 6 = 4.032` Punkte pro Tag. **60 vollständige
Tageskurven aller sechs Arme** benötigen 241.920 Punkte und 360 Captures und
bleiben innerhalb beider Größenlimits. Der Retentiontest prüft außerdem eine
kompakte JSON-Größe unter 40 MB für dieses synthetische Beispiel. Vier Arme
passen rechnerisch ungefähr 93 Tage in das Punktlimit, sechs ungefähr 62 Tage;
zusätzliche Stufen, Arme oder feinere Raster verkürzen die Dauer. 120 Tage sind
eine Obergrenze und keine zugesicherte Verfügbarkeit. Der Diagnostikzweig
`comparison_archive` nennt tatsächliche Punkte/Captures je Quelle, erste/letzte
Receipt und die aktive Capturepolitik.

Ein einzelner übergroßer oder zeitlich ungültiger Capture wird vor Mutation
abgewiesen. Ein unbekannter oder beschädigter Vergleichsstore bleibt unverändert
und schreibgeschützt; seine Daten werden nicht für den Vergleich freigegeben.
Bei einer validierten früheren Konfiguration beginnt das aktuelle Archiv leer
im RAM und wird erst nach erfolgreichem Setup und einem echten neuen Capture
schreibbar. Gültige Messintervalle, Haupt-Lernhistorie und Tagesstartwerte werden
dadurch nicht ungültig. Rohdaten bleiben privat im Store beziehungsweise in
einem ausdrücklich erstellten Export; die HA-Diagnostik gibt nur begrenzte
Umfangs-/Statusinformationen aus.

Das Archiv wird unabhängig vom häufigen Messdaten-Save geschrieben. Nach
vollständig erfolgreichem Setup startet ein neuer Tagescapture beziehungsweise
eine echte Pruneänderung einen eigenen asynchronen Save. Unveränderte Reloads
und fehlgeschlagenes Setup schreiben nichts. Kopie, JSON-Serialisierung und
Hashbildung laufen im Executor; der Eventloop trägt keine große JSON-Arbeit.
Erst ein SHA-geprüfter Disk-Readback bestätigt die gespeicherte Revision.
Ein durch HA intern nur protokollierter Schreibfehler bleibt diagnostiziert
und ungespeichert; ein späterer Versuch behält die ursprüngliche Receipt bei.
Beim Schließen wird ein laufender Save abgewartet und eine ausstehende zulässige
Änderung geschrieben. Der 30-Sekunden-Messdatentimer schreibt keine
Vergleichskurven mit.

## Verfügbarkeit und faire Evaluation

Konfigurierte beziehungsweise vorher bereitgestellte Arme bekommen auch dann
einen Capture, wenn ihre aktuelle Kurve fehlt. Ein `unavailable`-Capture enthält
keine Nullprognose; `partial` bezeichnet fehlende Stufen. Auch `available` ersetzt
keine Prüfung der vollständigen deklarierten Zielabdeckung.

Der Adapter in `scripts/evaluate.py` liest entweder den direkten
Vergleichsvertrag oder einen privaten JSON-Export dieses separaten HA-Stores.
Ein älterer isolierter Export unter `comparison_archive_v1` bleibt als
Adapter-Eingabehülle lesbar; er ist kein zusätzlich aktivierter Store. Für eine vollständig fehlende
Inverterkurve erzeugt er Null-Sentinels (`power_w=None`) auf den deklarierten
Fenstern. Hat der neueste Capture eine Kurve, aber eine Lücke im gewählten Ziel,
verwendet der Evaluator trotzdem diesen **neuesten verfügbaren Issue** und meldet
fehlende Prognose. Es gibt keinen Rückgriff auf einen älteren erfolgreichen
Capture. `None` wird nicht als Nullleistung bewertet.

Beispiel für einen vorab festgelegten Vergleichsauftrag in `data/schedule.json`:
Das vorhandene Evaluationseingabeformat behält `as_of`, `windows` und seine
Cutoffs. Istwerte stammen entweder ausschließlich aus `actuals` im
Eingabedokument oder aus `--actual-captures`. Mit `--actual-captures` muss
`actuals` fehlen oder eine leere Liste sein. Eine nichtleere Inline-Liste wird
mit einer Fehlermeldung abgelehnt: Ihre vollständige Qualitätshistorie ist
unbekannt. Sonst könnten ältere Inline-Labels trotz einer späteren negativen
Capture-Revision weiter bewertet werden. Reiner Inlinebetrieb bleibt möglich.
Die Quellen werden ausdrücklich gewählt, etwa
`["adaptive", "operative_baseline", "shadow:early_bias"]`; für einen anderen
Vergleich ergänzt oder ersetzt man sie durch einen konkreten `nwp:<model>`-Arm.
Ein Cutoff 18:00:00 kann einen erst um 18:07:12 archivierten Capture nicht nutzen.
Ein vorab festgelegter späterer gemeinsamer Cutoff muss diese tatsächliche
Verfügbarkeit berücksichtigen.

```bash
.venv/bin/python scripts/evaluate.py data/schedule.json \
    --comparison-archive data/private-history-export.json \
    --actual-captures data/actual-captures.jsonl \
    --output artifacts/model-comparison/report.json
```

Der Befehl liest nur und schützt Eingabedateien gegen Überschreiben. Es gibt
keinen automatischen Storeexport, produktiven HA-Zugriff oder Vergleichsstart.
Die vorhandene Evaluation verlangt weiterhin dieselben gemeinsamen Fenster,
Messgrenzen, vollständigen Istintervalle und Empfangs-/Ausgabecutoffs.
Abregelung, fehlende Labels und sonstige Qualitätsgrenzen bleiben sichtbar.
Keine automatische Modellgewichtung, Gewinnerauswahl oder Accuracybehauptung
folgt aus diesem Archiv. Tests stehen in `tests/test_comparison_archive.py`.
