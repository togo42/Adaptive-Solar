# Qualitätsableitung auf eingefrorenen Archiven messen

Stand: 03.11.2026. Diese Anleitung ergänzt die
[Bestandsaufnahme](performance-bestandsaufnahme.md) um eine Phasenmessung auf
einer vollständigen lokalen Archivkopie. Sie autorisiert keine Produktivprobe.
Originale, Quellenpolicy und operatorbezogene Ergebnisse bleiben unter
ignorierten lokalen Pfaden.

## 1. Quellen und Eingaben festlegen

[`scripts/profile_quality.py`](../../scripts/profile_quality.py) lädt die
Qualitätsimplementierung aus einem ausdrücklich angegebenen öffentlichen
Quellbaum. Das ist nötig, wenn der untersuchte Host einen anderen Stand als
der aktuelle Worktree verwendet. Das Quellenlabel beschreibt den gewählten
Commit; maßgeblich sind die zusätzlich erfassten Dateihashes und die geprüften
Importpfade. Alle Projektmodule müssen aus demselben Quellbaum stammen.

Einen frischen, cachefreien Quellbaum verwenden. Vorhandene `.pyc`-, `.pyo`-
oder `__pycache__`-Einträge werden abgelehnt: `-B` verhindert allein keine
Verwendung vorhandenen Bytecodes. Auch Pythondateien im Paket-Elternverzeichnis
werden erfasst. Ein vorhandener installierter Stand oder ein historischer
Ergebnisbericht ersetzt diesen Quellenabgleich nicht.

Benötigt werden eine lokale eingefrorene Archivkopie mit `index.sqlite3` und
allen Originalen, der unveränderte Rohcapture, die explizite Quellenpolicy und
eine passende Referenzausgabe. SQLite darf keine WAL-/Journal-/SHM-Sidecars
haben; eine laufende Datenbank einfach ohne ihr WAL zu kopieren ist kein
vollständiger Snapshot. Keine veränderliche produktive Archivwurzel übergeben.
Symlinks und überschrittene Budgets werden abgelehnt.
Vor der Messung müssen außerdem die Mengen der indexierten Batchhashes und
der Originaldateihashes exakt übereinstimmen. Unindexierte Originale könnten
Gegenbelege enthalten, die die normale Storeinitialisierung noch aufnehmen
würde. Der Helfer repariert den Index nicht, sondern verlangt einen vollständig
abgeglichenen Snapshot. Beide nativen Layouts und identische Hashdateien in
beiden Layouts während einer unterbrochenen Migration werden berücksichtigt.

Vorab bestimmen, ob der vollständige Originaleingabesatz der untersuchten
Hostprobe vorhanden ist. Ein fertiger Capturewrapper enthält nicht automatisch
alle Originale, die für dessen Qualitätsableitung gelesen wurden. Ein älterer
vollständiger Satz mit passenden Implementierungshashes ist ein eigener
lokaler Messfall, keine Wiederholung der späteren Hostprobe.

## 2. Lokale Messung starten

Eine geeignete vorhandene Pythonumgebung verwenden und Versionen prüfen.
Für den HA-freien Archivbetrieb ist die
[Archivhost-Umgebung](../archiv/archiv-host-installation.md) beschrieben;
die [Entwicklungsumgebung](entwicklung.md) eignet sich für die Helfertests.
Die Messworker blockieren HA-Imports und Netzwerkzugriffe. Ihre Umgebung
übernimmt ausschließlich Locale-/Pfad-/Zeitzoneneinstellungen und setzt vier
BLAS-/OpenMP-Threadlimits auf `1`; Zugangsdaten, Proxy-, Review- und
Pythonpfadvariablen werden nicht vererbt. Diese Threadlimits gehören zur
Messkonfiguration und sind kein Nachweis einer produktiven Parallelisierung.

Beispiel mit bereits vorbereiteten lokalen Kopien:

```bash
.archive-venv/bin/python -B -I scripts/profile_quality.py \
    --source-root artifacts/performance-source \
    --source-label SOURCE_COMMIT \
    --archive data/performance-input/archive \
    --raw data/performance-input/raw.json \
    --bindings data/performance-input/bindings.json \
    --output artifacts/performance-phases \
    --repeats 1 --timeout 900
```

`--output` muss ein neues Verzeichnis außerhalb der Eingaben und Quellen sein.
Die Standardeinstellung führt einen uninstrumentierten Referenzprozess und
danach einen separaten Phasenprozess aus. `--repeats 1..5` erhöht ausschließlich
die Zahl uninstrumentierter Prozesse. `--cprofile` ergänzt einen weiteren
eigenen Profillauf; insbesondere bei großen Originalen kann dieser deutlich
langsamer werden. Keine Tests oder weiteren Benchmarks parallel starten.

Der Helfer begrenzt den Aufbau auf höchstens 50.000 Originaldateien,
2.000.000 indexierte Ereignisse und 4 GiB komprimierte Originalbytes. Pro
JSON-Eingabe gelten 128 MiB. Die vorläufige Inventur entpackter Bytes nutzt
gzip-ISIZE und ist eine Ressourcenschätzung; die native Originalprüfung bleibt
zusätzlich aktiv. Der Standard für den virtuellen Prozessadressraum beträgt
4 GiB, der Worker-Timeout 900 Sekunden. Das Timeout ist höchstens 1.800
Sekunden; kleinere Mengen-/Zeitbudgets können explizit vorgegeben werden.

## 3. Phasen und Messgrenzen

Der lesende Adapter verwendet die native Originalprüfung, Ereignisselektion
und Payloadreferenzauflösung der gewählten Quellbasis. SQLite wird mit
`mode=ro`, `immutable=1` und `query_only` geöffnet. Die normale Storeinitialisierung,
Indexreconciliation und schreibende Lockdateien werden für diese eingefrorene
Kopie ersetzt. Diese Messung erfasst deshalb keine Lockwartezeit, Storeöffnung,
Kapazitätsinventur oder vollständige Archivhost-Jobdauer.

| Messpunkt | Inhalt |
| --- | --- |
| `wall_seconds`, `cpu_seconds` | Tatsächliche synchrone Ableitung ohne Imports, globale Eingabeinventur oder Ausgabeaufbereitung; mit explizitem Auswahlplan einschließlich dessen Eingangs-/Abschlussprüfung |
| `derive_to_build_wall_seconds` | Rohprüfung, Quellscan, Selektion, Konfigurationsaufbereitung und Payloadauflösung vor Eintritt in `build_quality` |
| `quality.build_quality` | Qualitätskern einschließlich Ereignis-/Bindungsprüfung, Intervallaufbereitung, Stundenentscheidungen und Evidenzhashes |
| `build_to_derive_end_wall_seconds` | Nachgelagerte Provenienzergänzung und Capture-Normalisierung im untersuchten `derive` |
| `archive.iter_events_next` | Zeit ausschließlich in `next()` des nativen Generators; Arbeit des aufrufenden Consumers zählt nicht dazu |
| `archive._read_original`, `gzip.read`, `json.loads` | Originallesen/-prüfung sowie darin überlappend Dekompression und Parsing |
| `archive.validate_page`, `archive.validate_envelope`, `archive.canonical_bytes` | Überlappende Validierungs- und kanonische Serialisierungskosten |
| `archive._validate_original_page`, `archive._validate_original_envelope`, `archive._canonical_json_bytes` | Zusätzliche Labels für den privaten Originalpfad, soweit im gewählten Quellstand vorhanden; der strenge Seitenscan bleibt darin enthalten |
| `quality.configuration_from_forecast` | Erneute Originalprüfung und Aufbereitung kompakter Konfigurationsbelege, soweit im Quellstand vorhanden |
| `quality._intervals`, `quality._hour` | Vorbereitung je Bindung und Kandidatenprüfungen der Stundensuche |

Die drei groben Abschnitte vor, in und nach `build_quality` beschreiben die
Ableitung in zeitlicher Reihenfolge. Alle übrigen Wrapperzeiten sind inklusiv
und verschachtelt; sie dürfen nicht aufsummiert werden. Zähler berichten unter
anderem tatsächlich gelesene Originalbytes/-ereignisse, Konfigurationsbelege,
vorbereitete Intervalle und mit `interval_candidates` die vollständige je
Stunde geprüfte Eingangsliste, nicht nur überlappende Treffer. Gesamtarchivgröße
und tatsächlich gelesene Quellenmenge sind getrennte Größen.

Imports und Dateihashprüfung liegen vor der inneren Laufzeitmessung.
Die vollständige Byteinventur wärmt den Betriebssystemcache vor. Frische Worker
beweisen hier keinen kalten Dateicache. `process_peak_rss_kib` erfasst die
gesamte Prozessspitze; die äußere Prozesszeit enthält auch Imports,
Integritätsprüfung und Ergebnisausgabe. Sie ist nicht die native Hostjobzeit.
Phasenwrapper und cProfile verursachen eigenen Aufwand; die uninstrumentierte
Referenz bleibt deshalb der Laufzeitbeleg. Bei wenigen Läufen keine p95 ableiten.

## 4. Integrität und Ergebnisvergleich

`input-manifest.json` bindet sämtliche Archivdateien, Rohcapture, Policy und
Python-/JSON-Quellen. `environment.json` erfasst Interpreter, Abhängigkeiten,
Hardware, Befehlszeile und Messhelferhash. Die Hashinventur wird vor und nach
jedem Worker sowie nach dem gesamten Ablauf wiederholt. Gefrorene Dateien
werden nicht überschrieben. `summary-N.json` ist ausdrücklich ein Zwischenstand;
erst `complete.json` belegt einen vollständig abgeschlossenen Ablauf.

Reale `as_of`- und Abschlusszeiten bleiben real. Der Helfer kontrolliert die
Übereinstimmung von `generated_at`, `validated_at` und `normalized_at` sowie
die tatsächliche Verfügbarkeit normalisierter Records. Die Originalreceiptzeit
und Capture-ID müssen erhalten bleiben. Vollständige Ergebnishashes dürfen
wegen neuer Abschlusszeiten abweichen.

`decision_sha256` vergleicht zusätzlich alle stabilen Capture- und Reportfelder,
Original-/Konfigurations-/Implementierungspins, Stundenentscheidungen,
Qualitätsmasken, Messwerte und Ausschlüsse. Nur neue Ableitungs-/Verfügbarkeitszeiten
und davon abhängige Qualitätsprovenienz werden für diesen zusätzlichen Vergleich
ausgeklammert. Die Originale und vollständigen Ergebnishashes behalten sie.
Abweichende fachliche Ergebnisse brechen den Ablauf ab; sie werden weder
weggerundet noch nachträglich durch eine historische Uhr erzwungen.

Eine ältere Referenzausgabe nur nach Prüfung ihrer Implementierungshashes
heranziehen. Gleiche angenommene Stunden bei verschiedenen Quellständen sind
noch keine vollständige Provenienzgleichheit. Operatorbezogene Vergleichsbelege
und konkrete Laufzeittabellen gehören unter `data/docs/betrieb/`.

## 5. Aus Messung einen Kandidaten ableiten

Der erste lokale [Kandidat zur Originalvalidierung](performance-originalvalidierung.md)
behält den vollständigen strengen Seitenbaumdurchlauf bei und vermeidet nur
die beiden nachfolgenden Schlüsselbaumdurchläufe je Envelope. Öffentliche
Validatoren, Prüfsummen, Formate und Grenzen bleiben erhalten.

Den ersten Optimierungskandidaten anhand des größten bestätigten Kostenanteils
wählen. Für Originallesen, Validierung, Selektion, Konfigurationsaufbereitung
und Stundenprüfung zunächst unterschiedliche Ursachen annehmen und durch
gezielte Messung unterscheiden. Eine pauschale Rust-Portierung oder das
Entfernen wiederholter Prüfungen ist daraus nicht autorisiert.

Eine spätere Optimierung muss an derselben eingefrorenen Eingabe gegen die
unveränderte Referenz geprüft werden. Die Abnahme schützt Originalbytes,
Quellen-/Generations-/Konfigurations-/Producerpins, vollständige Gegenbelege,
Einheiten, Lücken, Gates, DST-Verhalten und echte Verfügbarkeit. Die Regeln der
[Übergabe](performance-uebergabe.md#4-messung-und-abnahme) gelten weiterhin.

Der zusätzliche [Auswahlprototyp](performance-archivauswahl.md) bindet einen
einmal vollständig geprüften Archiv-/Abfragesatz. `--selection-plan` verlangt
zusätzlich `--selection-plan-sha256`; beide Optionen sind ausschließlich für
die ausdrücklich gebundene lokale Wiederverwendung vorgesehen. Beide
Byteprüfungen des Auswahlscopes liegen innerhalb seiner gemessenen Laufzeit.
Entsprechend enthält `derive_to_build_wall_seconds` dann auch Planlesen und
Eingangsprüfung; `build_to_derive_end_wall_seconds` enthält zusätzlich die
Abschlussprüfung. Diese beiden Marker sind mit Plan keine reinen
Verbraucherphasen. `selection_status` zeigt die tatsächlich geplanten
Batchbesuche und Headroom-Fallbacks; geplante Besuche sind keine separaten
I/O-Messungen.
Der Kaltaufbau gehört als eigener Messfall zum Vergleich. `collection_evidence`
projiziert nach dem Timing zusätzlich die im Quellstand verfügbaren Original-
und Konfigurationsbelegzähler/-hashes; der vollständige stabile Entscheidungs-
hash bleibt die maßgebliche Gleichheitsprüfung.

Der getrennte [Rustversuch](performance-rust-probe.md) nutzt stattdessen
`--rust-module PATH --rust-module-sha256 SHA256`. Binärdatei und Adapter werden
zusätzlich gebunden; Import, AST-Aufbau und abschließende Pinhashes bleiben
außerhalb der inneren Ableitungszeit. Rustlesen, Pythondekodierung und native
Fallbacks liegen innerhalb. `rust_probe` berichtet deren tatsächliche Zähler
und die qualifizierten Quellen. Beide Optionen verlangen einen eigenen Arm
ohne Auswahlplan; der normale Reader bleibt der Standard.
