# Lokale Performance-Bestandsaufnahme

Stand: 02.11.2026. Ausgangscommit `7fd32b2` im separaten Worktree;
gegenüber der [Übergabebasis](performance-uebergabe.md) `83ea45b` sind nur die
Übergabe und deren Navigation hinzugekommen. Der Integrations- und Hostcode
wurde für diese Bestandsaufnahme nicht geändert. Drei Subagenten bearbeiteten
Probezuordnung, Codebestand und Messhelfer; ein weiterer Prüfdurchgang bewertete
den Messhelfer unabhängig.

## 1. Bestand und Abgrenzung

Die Bestandsaufnahme bestätigt folgende Strukturen im untersuchten Checkout:

| Bereich | Bestätigter Aufwand | Messstatus |
| --- | --- | --- |
| `ArchiveStore.__init__` | SQLite-Integritätsprüfung und Inventur der Originaldateien | Lokal getrennt erfasst |
| `continuous_quality.derive` | Alle Batches je gebundener Quelle lesen und prüfen, anschließend Zeitraum und Ereignisarten filtern | Lokal mit wachsender Historie erfasst |
| `actual_quality.build_quality` | Ereignisprüfung, Intervallaufbereitung, Hashbildung und vollständige Intervallsuche pro Zielstunde | Im separaten Profil enthalten |
| Trainingsjoin | Aufbereitung und Messindex vor dem Vergleich der Fit-Signatur | Codebefund; hier nicht gemessen |
| Coordinator/Export | Hauptprognosezeit endet vor Bias-Shadow, Einzelmodellphysik und Exportaufbereitung | Codebefund; hier nicht gemessen |
| Ereignisloop | Historienkopien und wiederholtes Prune | Codebefund; hier nicht gemessen |
| Archivhost | Gemeinsamer Writerlock und Kapazitätsprüfung über Dateiinventur | Codebefund; kein neuer Hostlauf |

Die zusätzlich gelesenen privaten Betriebsbelege unterscheiden eine
sperrdominierte Diagnoseprobe und eine aufwendige Qualitätsableitung.
Nach Nutzerpräzisierung und erneutem Belegabgleich ist der Untersuchungsanlass
dem vollständigen nativen Istwert-Pilotlauf zugeordnet. Die kürzere
sperrdominierte Diagnoseprobe war ein anderer Lauf; deren Lockanteil erklärt
die Laufzeit des vollständigen Piloten nicht. Der passende Receipt enthält
Gesamtzeit und native Jobzeit. Die zugehörige frische Qualitätsprüfung liefert
außerdem die chronologischen Endpunkte `as_of` und `validated_at`: Der weitaus
größte Teil des Laufs liegt zwischen diesen beiden Zeitpunkten. Das grenzt den
ersten Prüfbereich auf die Qualitätsableitung ein, ist aber keine Messung von
CPU-Zeit oder einzelnen Unterphasen. Getrennte Zeiten für Lockwartezeit,
Netzwerk, Originalprüfung, Auswahl, Qualitätskern, Stats und Kapazitätsprüfung
fehlen weiterhin.
Gesamtzeiten, Eingaben, Befehle, Archivvolumen und Installationsdetails bleiben
in der privaten Betriebsdokumentation. Dieser Beleg ist noch kein vollständiges
Hostprofil. Der belegte Hostquellstand unterscheidet sich außerdem in der
Konfigurationsaufbereitung vom hier gemessenen Checkout.

## 2. Reproduzierbarer lokaler Messaufbau

[`scripts/benchmark_quality.py`](../../scripts/benchmark_quality.py) erzeugt
ein neues synthetisches Archiv und einen synthetischen Recorder-Capture. Eine
Quelle und eine Bindung liefern Energieintervalle von jeweils 60 Sekunden.
Das Ziel bleibt bei 24 UTC-Stunden; zusätzliche Historientage liegen davor.
Die Policy und alle Quellenpins sind ausdrücklich synthetisch, keine physische
Quellenqualifikation. Ein Lerner ist nicht aktiv.

Nach Einrichtung der [Entwicklungsumgebung](entwicklung.md):

```bash
.venv/bin/python scripts/benchmark_quality.py \
    --output artifacts/performance-baseline \
    --days 1 7 30 --repeats 5
```

Der Helfer akzeptiert nur ein neues Ausgabeverzeichnis. Er hält Rohcapture,
Policy, Originaldateihashes, Ereignis-/Batchzahlen, komprimierte Bytes,
Zielzeitraum, Interpreter, Abhängigkeiten, Hardware und Quellhashes fest.
Die generierten Eingaben werden vor jeder Wiederholung geprüft; die Originale
müssen nach der Messung bytegleich sein. Mehrere frische Prozesse messen ohne
Profiler. Ein zusätzlicher Prozess erzeugt `profile.prof`, `profile.txt` und
Original-Lesezähler. Profilzeiten werden getrennt von den Vergleichszeiten
ausgewertet.

Vor dem Anlegen der Fixtures begrenzt er den gesamten Aufbau auf 100.000
Ereignisse und 1.000 Batches über alle gewählten Historiengrößen. Diese Grenze
schützt auch die Fixture-Erzeugung: Der native Ingest inventarisiert bestehende
Originale bei jedem Batch erneut. Ein Timeout nur für Messprozesse würde diesen
vorgelagerten Aufwand nicht begrenzen. Jeder Messprozess hat zusätzlich ein
Timeout von 180 Sekunden.

Die innere Messung beginnt nach Imports und Eingabeprüfung. Sie trennt
Store-Öffnen und `derive`, jeweils mit Wall- und CPU-Zeit. Die äußere
Prozesslaufzeit schließt auch Start, Imports, Eingabeprüfung und Ausgabe ein.
Fixture-Erzeugung und übergeordnete Ablaufsteuerung liegen außerhalb dieser
Prozesslaufzeit; sie ist kein End-to-End-Profil eines Archivhostjobs.
Spitzen-RAM bezeichnet die gesamte Prozessspitze einschließlich dieser Arbeit.
Der Betriebssystemcache ist durch die Integritätslesung vorgewärmt; frische
Pythonprozesse sind hier kein Nachweis eines kalten Dateicaches.

Nur die beiden Qualitätsmodule erhalten eine kontrollierte synthetische
`datetime.now`-Uhr. `perf_counter` und CPU-Uhr bleiben real. Vollständige
Ergebnishashes müssen innerhalb derselben Fixture einschließlich des
Profillaufs übereinstimmen. Über die Historiengrößen werden Stundenentscheidungen,
Masken, Zusammenfassungen und normalisierte Werte verglichen. Unterschiedliche
Evidenz-IDs und deren Provenienz werden nur für diesen zusätzlichen fachlichen
Vergleich ausgeklammert, nicht aus Originalen oder vollständigen Ergebnishashes
entfernt. Echte Qualitätsableitungen werden damit nicht zurückdatiert.

## 3. Lokale Baseline

Gemessen unter Python 3.14.4 auf AMD Ryzen 7 PRO 5850U, 16 logischen CPUs,
WSL2/Linux 6.18.33.2. Installiert waren pvlib 0.16.1, scikit-learn 1.9.1,
NumPy 2.3.2, Pandas 2.3.3 und aiohttp 3.14.5. Verwendet wurde die vorhandene
Entwicklungsvenv; es wurde nichts installiert. Die Rechenpfade sind synchron,
es gab keine parallel gestarteten Benchmark- oder Testprozesse dieser Sitzung.

Je Historiengröße: fünf uninstrumentierte Wiederholungen und ein separater
Profillauf. Jede Tabellenzeit und der Prozesspeak sind jeweils der Median
der fünf uninstrumentierten Läufe; eine belastbare p95 wird nicht angegeben.

| Historientage | Gelesene Batches / Events | Komprimierte Originalbytes | Öffnen (s) | Ableitung (s) | Öffnen + Ableitung CPU (s) | Äußerer Prozess (s) | Prozesspeak (MiB) |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 1 | 15 / 1.441 | 97.905 | 0,0038 | 0,254 | 0,257 | 1,974 | 211,7 |
| 7 | 101 / 10.081 | 679.609 | 0,0143 | 0,721 | 0,733 | 2,427 | 212,8 |
| 30 | 433 / 43.201 | 2.911.157 | 0,0411 | 2,529 | 2,572 | 4,232 | 228,0 |

Öffnen und Ableitung zusammen benötigten im Wall-Median 0,257 / 0,734 / 2,572
Sekunden. Für die Ableitung lagen die fünf Einzelwerte bei 0,248–0,259 /
0,707–0,740 / 2,505–2,744 Sekunden. Zusätzliche Historie verzehnfacht in diesem
Aufbau die Ableitungszeit zwischen einem und 30 Tagen, obwohl nur derselbe
Zieltag ausgewertet wird. Das ist ein Skalierungsbefund des aktuellen Codes,
keine gemessene Beschleunigung eines Kandidaten.

Alle 18 Prozesse lieferten jeweils 24 angenommene Zielstunden; die fachlichen
Entscheidungen waren über alle drei Historiengrößen gleich. Innerhalb jeder
Fixture waren auch die vollständigen Ergebnishashes einschließlich des
Profillaufs identisch. Eingabe- und Originalbytes blieben erhalten; nach dem
Lauf wurden sämtliche erfassten Python-Quellhashes erneut unverändert gelesen.

Der 30-Tage-Profillauf brauchte für Öffnen und Ableitung 6,175 Sekunden und
zeigt damit erheblichen Profilingaufwand gegenüber den uninstrumentierten
Läufen. Innerhalb dieses Profils entfielen kumulativ:

| Funktion | Aufrufe | Kumulative Profilzeit (s) |
| --- | --- | --- |
| `ArchiveStore._read_original` | 433 | 5,315 |
| `validate_page` | 433 | 4,936 |
| `canonical_bytes` | 95.486 | 4,331 |
| `build_quality` | 1 | 0,318 |
| `json.loads` im Messbereich | 433 | 0,151 |
| `gzip.GzipFile.read` | 433 | 0,147 |
| `_hour` | 24 | 0,0064 |

Diese inklusiven Zeiten überlappen; sie dürfen nicht addiert werden.
Originalprüfung einschließlich kanonischer Validierung dominiert den großen
synthetischen Fall. Die Stundensuche ist bei den hier ausgewählten 1.440
Intervallen ein kleiner Anteil. Daraus folgt kein entsprechender Anteil bei
mehr Bindungen, dichterer Messung, großen Forecastpayloads oder einem anderen
Quellstand. Payloadauflösung, Widerspruchsgenerationen und aktive ML wurden mit
dieser einfachen Fixture nicht als Leistungsfälle untersucht.

Die lokalen Rohartefakte liegen unter
`artifacts/performance-20261102-final/`: `environment.json`, `summary.json`,
je Fixture `fixture.json`, `raw.json`, `bindings.json`, `run-1.json` bis
`run-5.json` und `profile.json`/`.prof`/`.txt`. Sie sind nicht versioniert und
werden für die Anleitung nicht vorausgesetzt. Der dort gebundene Messhelfer
hat SHA256
`fe02568095fc27edc36f44640b0216df90eeb21d34c4ba9015aa3ea016afd3b8`.
Frühere Smoke- und Vorabmessungen sind kein zusätzlicher Vergleichsarm.

Validierung: 79 gezielte Tests für Messhelfer, fortlaufende Qualitätsableitung
und Qualitätskern bestanden ohne Skips, einschließlich der vorhandenen
DST-Fälle. Die neuen Helfertests prüfen gleiche Entscheidungen trotz größerer
Historie, vollständige Ergebnisgleichheit mit/ohne Profiler, Originalerhaltung,
Dateibytebindung und Ablehnung unzulässiger Aufbaubudgets. Ein unabhängiger
Reviewbefund zur zu großen erlaubten Fixture-Erzeugung wurde mit dem oben
genannten Gesamtbudget und Regressionen behoben. Produktive Implementierung,
Datenverträge und Anwenderverhalten blieben unverändert.

## 4. Nächster begründeter Schritt

Die Gesamtlaufzeit des identifizierten nativen Istwert-Pilotlaufs in Phasen
zerlegen. Seine Originalmenge und Payloadstruktur unterscheiden sich erheblich
von der kleinen synthetischen Baseline; ein Laufzeitverhältnis zwischen diesen
beiden Aufbauten wäre kein Beschleunigungsnachweis. Timerpausierung allein
beweist keine Lockwartezeit von null.

Zunächst die Kosten der Originalprüfung und der erst anschließenden
Zeitselektion auf einer begrenzten eingefrorenen realen lokalen Kopie getrennt
erfassen. Den passenden Quellstand einschließlich der bereits vorhandenen
kompakten Konfigurationsbelege verwenden und das Ergebnis gegen dessen Referenz
prüfen. Laufzeit einer Diagnoseprobe muss weiterhin Wartezeit und eigene Arbeit
getrennt berichten.

Erst danach eine gezielte Batchauswahl als einzelnen Optimierungskandidaten
bewerten. Konfigurationsanker, referenzierte Payloadteile, Gegenbelege aus
anderen Generationen, Originalprüfung und Auswahlbudgets bleiben erforderlich.
Ein schnellerer Vollscan erlaubt keinen Verzicht auf diese Evidenz. Ein Profil
mit vielen Aufrufen der kanonischen Serialisierung ist ebenfalls keine
Freigabe, Prüfungen oder Hashbindungen zu entfernen.

Coordinator-Worker, aktive ML-Vorhersagen, Export, Ereignisloop-Latenz,
Netzwerk, Kapazitätsprüfung und produktive Locks sind weitere getrennte
Messaufträge. Aus diesem lokalen Start folgen keine produktiven Änderungen,
keine Rust-Entscheidung und keine Aussage über Prognosegüte.
