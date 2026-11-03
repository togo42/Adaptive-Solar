# Begrenzte Laufzeittelemetrie für Archivjobs

`scripts/runtime_metrics.py` liefert eine Standardbibliothek-basierte
`PhaseRecorder`-API. `scripts/archive_host.py` verwendet sie für den vorhandenen
Repository-Runner einschließlich der getrennten Jobs `actuals` und
`references` und des kompatiblen kombinierten Jobs `observations`. Ein temporärer Messaufsatz muss den tatsächlich
installierten Quellstand und dessen unveränderte Qualitätsgates binden.

## Phasen und Zeitbasis

`PhaseRecorder(job, run_id=..., sink=..., clock=..., cpu_clock=...)` akzeptiert
nur begrenzte Jobnamen und feste Phasenlabels. Der Contextmanager
`phase(label, ordinal=..., timeout_seconds=..., emit_events=True)` misst die
wirklich umschlossene Ausführung. `process(label, function, *args, **kwargs)`
beobachtet den ursprünglichen Prozessaufruf; Argumente, Umgebungen und Ausgaben
werden weder übernommen noch serialisiert. `lock_file(handle)` schließt den
ursprünglichen Lockhandle und misst diesen tatsächlichen Abschluss.

Die Elternphasen sind Locköffnung, Lockwartezeit, Vorbereitung,
Kapazitätsprüfung, Kindaufruf, Statistik, Ergebnisschreiben und Lockschluss.
Zusätzliche feste Labels erlauben Storeinitialisierung, Indexabgleich,
Originallesen, Recorderabruf, Recovery, Qualitätsableitung, Quellenscan,
Konfigurationsprojektion, Qualitätsbau, Archivanhang, Collection,
Payloadauflösung und Normalisierung. Sie werden erst durch explizite
Instrumentierung der betreffenden Aufrufe gefüllt; das Modul allein misst
keine Kindphasen.

`duration_ns` und `elapsed_ns` verwenden `time.monotonic_ns`.
`duration_cpu_ns`, aggregiertes `cpu_ns` und `process_cpu_elapsed_ns` verwenden
`time.process_time_ns`. Die CPUwerte gehören ausschließlich zum aktuellen
Prozess. Insbesondere enthält die Elternphase `child_run` keine CPUzeit des
Kindes. Ein eigener Recorder im Kind kann dessen ProzessCPU messen. Wandzeit
und CPUzeit verschachtelter oder überlappender Phasen sind inklusiv und dürfen
nicht als Gesamtlaufzeit addiert werden. UTC-Zeitstempel dienen nur der
zeitlichen Zuordnung.

Bei wiederholter Livepublikation im Messaufsatz kann bereits angefallene
Publikationsarbeit einschließlich des Hintergrundthreads in späteren Wand-
und ProzessCPUwerten enthalten sein. Der Recorder zieht diesen Aufwand nicht
rechnerisch ab. Die laufende Veröffentlichung eines Snapshots ist zum Zeitpunkt
seiner Erstellung noch nicht abgeschlossen und erhält keinen eigenen Span.

## Begrenzung, Fehler und Zwischenstände

`phase_summary` aggregiert alle abgeschlossenen Phasen. Der Detailring enthält
standardmäßig höchstens die letzten 512 Spans; verlorene Details werden gezählt.
Häufige Aufrufe wie `original_read` können `emit_events=False` verwenden:
Aggregierung und `active_phases` bleiben erhalten, Detailring und Ereignissink
werden geschont. `snapshot()` liefert unabhängige Kopien einschließlich aktuell
aktiver Phasen. Deren Dauer und Ergebnis bleiben offen; ein Prozessabbruch
wird nicht als erfolgreicher Phasenabschluss erfunden. Livepublikation und deren
Rate begrenzt der jeweilige Aufsatz separat.

Die festen Fehlerklassen sind `timeout`, `os_error`, `invalid_data`,
`interrupted` und `internal_error`; hinzu kommen `completed` und `nonzero_exit`.
Native Ausnahmen werden weitergereicht. Prozessstatus unterscheidet `exited`,
`timeout`, `os_error` und für andere Ausnahmen `raised`. Rückgabecode und
konfiguriertes Timeout sind getrennte Zahlenfelder. Weder Ausnahmeinhalt noch
`argv`, Umgebungswerte, stdout, stderr, Quellenidentitäten oder Nutzdaten gelangen
in die Telemetrie. Ein fehlerhafter Ereignissink wird gezählt und löst keinen
zweiten fachlichen Aufruf aus.

## Statuskorrelation und Abschluss

Der bestehende `JOB.json`-Nachweis erhält lediglich einen Verweis
`runtime_metrics` mit Schema, `run_id` und dem festen Dateinamen
`JOB-runtime.json`. Prozessstatus erhält additive `exit_kind`- und
`timeout_seconds`-Felder. Das bisherige Feld `failed_or_timed_out` bleibt bei
fehlgeschlagenem Kindstart beziehungsweise Timeout erhalten; die neue Kategorie
trennt die beiden Fälle. Die Statistik besitzt ihren eigenen `stats_process`.
Die sieben übernommenen Archivstatistiken müssen endliche nichtnegative
Zahlen sein; boolesche Werte, Text und verschachtelte Inhalte werden als
ungültige Statistik behandelt und nicht in den Status kopiert.

Der Runtime-Nachweis wird nach dem wirklichen Schreiben des fachlichen Status
und dem Schließen des Writerlocks atomar veröffentlicht. Er enthält dadurch
`result_write` und `lock_close`. Seine eigene Veröffentlichung ist ausdrücklich
von `elapsed_ns` ausgenommen: Ein Dokument kann die abgeschlossene Dauer seines
eigenen Schreibens nicht enthalten. `job_complete` und `run_exit_kind` trennen
das fachliche Ergebnis vom normalen beziehungsweise außergewöhnlichen Ende der
Elternfunktion. Auch bei einer Ausnahme können bereits abgeschlossene Phasen
publiziert werden; bei hartem Prozessabbruch gibt es keine garantierte finale
Datei.

Verbraucher dürfen nur Nachweise mit identischer `run_id` zusammenführen.
Fehlende, veraltete oder durch einen parallelen späteren Lauf ersetzte Sidecars
sind eine Telemetrielücke. Ein Sidecar-Schreibfehler ändert weder das fachliche
Jobresultat noch startet er die Erfassung erneut; es erscheint nur eine feste
bereinigte Warnung. Sämtliche festen Status-, Runtime- und Lockpfade werden vor
Verzeichnisanlage gegen Archiv, Programm und konfigurierte Eingabedateien
geprüft. Originaldaten und vorhandene Kapazitäts-/Qualitätsgates bleiben
unverändert.

Die Regressionen stehen in `tests/test_runtime_metrics.py` und
`tests/test_archive_host.py`. Sie prüfen monotone Wandzeit und ProzessCPU,
Timeout-/Startfehler, Teilergebnisse, tatsächliches Schreiben und Schließen,
begrenzte Details, Geheimnisfreiheit und die bestehenden Ausgabeschutzgrenzen.

## Gepinnte bestehende Installation einmal beobachten

[`scripts/archive_runtime_trace.py`](../../scripts/archive_runtime_trace.py)
und [`tools/archive_runtime_trace/sitecustomize.py`](../../tools/archive_runtime_trace/sitecustomize.py)
ermöglichen einen ausdrücklich eingerichteten temporären Messaufsatz. Die
vorhandenen Programmdateien werden dabei nicht geschrieben. Der Aufsatz bindet
die neun vollständigen Dateihashes aus `SOURCE_FILES`, drei Helferdateien,
einen getrennten Telemetrieordner, eine gemeinsame `run_id` und den ursprünglichen
`sitecustomize`-Hook in einem Manifest des Schemas
`adaptive-solar-pinned-runtime-trace-v1`.

Die explizite Umgebung verwendet `ADAPTIVE_SOLAR_RUNTIME_TRACE` für den
absoluten Manifestpfad und `ADAPTIVE_SOLAR_RUNTIME_TRACE_SHA256` für seinen
externen Hash. Der Bootstrap liegt vorübergehend auf `PYTHONPATH`. Vorher
müssen vorhandene Pfade, EnvironmentFiles und native Bootstrapfunktionen
geprüft und erhalten werden. Der ursprüngliche Hook läuft zuerst mit seiner
ursprünglichen Modulidentität. Nur Fehler der zusätzlichen Telemetrie führen
zu einer festen Warnung und unveränderter nativer Ausführung.

Vor dem nativen letzten Main-Aufruf wird die Startupverfolgung abgeschaltet.
Danach werden nur überprüfte Funktionscodes instrumentiert; die Entfernung
der Instrumentierung muss jeweils den gesamten ursprünglichen AST ergeben.
Dekoratoren, Defaultargumente und Annotationen werden nicht erneut ausgeführt.
Bei unvollständiger Installation werden Codes und temporäre Globals
transaktional zurückgesetzt. Originallesen und Projektion behalten ihre
nativen Funktionsrahmen. Die drei unterstützten Einstiegspunkte sind
`archive_host.py`, `archive_observations.py` und `archive.py`.

Jeder instrumentierte Prozess schreibt höchstens alle fünf Sekunden seinen
begrenzten atomaren Sidecar. Auch bei einem Kindtimeout kann dadurch ein
Zwischenstand mit offenen Phasen erhalten bleiben. `process_status=finished`
belegt den Abschluss der Telemetriepublikation; den fachlichen Exitstatus
belegen weiterhin Elternprozess beziehungsweise systemd. Die eigentlichen
Statusdateien des installierten Runners bleiben unverändert.

Vor einem Dienststart müssen instrumentierte `--help`-Aufrufe erfolgreich
enden und vollständige AST-/Hashmarker im Sidecar erzeugen. Ein Aufsatz ohne
Marker ist keine gültige Messung, auch wenn das Programm erfolgreich endet.
Temporäre Dienstumgebung nur mit abgesichertem Rückbau einrichten: Verbindung
oder zeitliche Lease verlieren, Abbruch und Fehler dürfen keinen späteren
regulären Lauf unbeabsichtigt instrumentieren. Nur den eigenen Dropin
entfernen, den Manager neu laden und seine Abwesenheit nachlesen. Ein
manueller zusätzlicher Dienststart braucht einen konkreten Betriebsauftrag;
Timer, Timeouts und Qualitätsgrenzen bleiben dabei erhalten.

Die Bootstrap-, AST-, Hook- und Rücksetzungsregressionen stehen in
`tests/test_archive_runtime_trace.py`. Konkrete Hostmanifest-, Transfer-,
Laufzeit- und Rückbaubelege gehören in die ignorierte Betriebsdokumentation.
