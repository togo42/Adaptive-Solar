# Native Auswahl und Konfigurationsprojektion prüfen

Stand: 03.11.2026. Dieser optionale Entwicklungsversuch erweitert den
[Rust-Originalreader](performance-rust-probe.md). Er ist kein produktiv
aktivierter Archivreader und keine Abhängigkeit der HA-Integration.

## 1. Ziel und erhaltene Evidenz

Der Originalreader spart Validierungsschleifen, baut anschließend aber weiterhin
alle Pythonereignisse auf. Der neue Kern `project_quality_source` prüft ebenfalls
in jedem Lauf sämtliche indexierten Originalbatches der abgefragten Quelle.
Er übergibt nur relevante Intervalle und verifizierte Konfigurationsbelege an
Python. Ein persistierter Auswahlindex oder Validierungscache wird nicht benutzt.

Die native SQLite-Reihenfolge und die Deduplizierung nach Quelle, Generation
und Sequenz bleiben erhalten. Dedupliziert wird vor der Auswahl nach Art und
Zeit. Alle Generationen, Anker außerhalb der Bindungsperiode und künftige
Empfangszeiten bleiben berücksichtigt. Die echte `as_of`-Grenze prüft weiterhin
der Pythonverbraucher. Bei Payloadreferenzen oder unbekannten Strukturen fällt
die gesamte Quelle auf ihren ursprünglichen Pythoniterator zurück; ein
teilweises Ergebnis wird nicht ausgegeben.

Inline-Konfigurationen werden als unveränderliche native Objekte ohne
öffentlichen Konstruktor übergeben. Ihre kompakten kanonischen Belegbytes
müssen bytegenau dem qualifizierten Pythonhersteller entsprechen. Zusätzlich
erhalten bleiben vollständige Originalreferenz, ursprüngliche Batchprüfsumme
und kanonische Größe des vollständigen Arbeitsereignisses. Das bisherige
Arbeits- und Aufbewahrungsbudget wird dadurch nicht durch die kleinere
Beleggröße ersetzt. Ein JSON-Dictionary kann keine solche Berechtigung erzeugen.

Das Projektionsprotokoll 2 gibt erst nach vollständiger Quellenvalidierung
einen einmalig konsumierbaren nativen Iterator aus. Verbrauchte Bytepuffer
werden freigegeben, statt sämtliche PyBytes einer Quelle bis zum Ende ihrer
Dekodierung in einem Tupel zu halten. Die Berechtigungsregistrierung verwendet
schwache Referenzen. Beim Dekodieren werden ausschließlich 22 feste
Envelope-/Intervall-Vertragsschlüssel geteilt; beliebige Eingabeschlüssel und
Werte werden nicht global interniert. Das vermeidet den zusätzlichen
Schlüsselspeicher durch einen separaten JSON-Aufruf je Ereignis und erhält
alle Werte und kanonischen Bytes. `read_original` behält Protokoll 1.

## 2. Qualifizierter Verbraucher und Grenzen

[`scripts/rust_quality_projection.py`](../../scripts/rust_quality_projection.py)
bindet vier vollständige Quelldateihashes des qualifizierten kompakten
Verbrauchers aus dem öffentlichen Gitstand
`2dd940c3aa1a00d7291228f24ebaac90b56eef14`. Maßgeblich bleiben die vier
Hashes in `COMPACT_SOURCES`; der separat qualifizierte Archivreader und die
beiden Rustadapter werden zusätzlich eingefroren. Ein Export dieses
öffentlichen Gitstands benötigt keine privaten Installationsdateien.
Der ältere Verbraucher im Repository wird ausdrücklich nicht
unterstützt. Ein Versuch benötigt einen separat eingefrorenen öffentlichen
Quellbaum mit genau diesen vier Dateien und dem optionalen Adapter. Ihre
Dateibytes und die resultierenden Implementierungsnachweise bleiben erhalten.
Es wird keine produktive Installation durch einen älteren Checkout ersetzt.

Der Adapter ergänzt den vorhandenen Projektionseinstieg durch einen überprüften
AST-Zweig im bisherigen Funktionsrahmen. Nach Entfernen dieses Zweigs muss der
gesamte ursprüngliche AST identisch sein. Defaultargumente, Dekoratoren und
Annotationen werden nicht erneut ausgeführt. Die Berechtigung gilt nur für
native Objekte des laufenden Scopes, dieselbe vollständige Bindungspolicy und
den jeweiligen Ankerstatus. Funktionen und temporäre Globals werden danach
wiederhergestellt. Quellen, Binärdatei, Runtime und Eingaben werden abschließend
erneut gebunden.

Das Projektionsprotokoll unterstützt CPython 3.14, die ausdrücklich
qualifizierten Archivreader und höchstens 50.000 Originaldateien,
2.000.000 gescannte Ereignisse, 500.000 ausgewählte Ereignisse und 512 MiB
internes Projektionsbudget. Unbekannte Formen führen zum vollständigen nativen
Fallback; Signale und Abbrüche dürfen dabei nicht verschluckt werden.

## 3. Getrennte Prüfungen und Messung

Die normalen Adaptertests benötigen keinen Rustcompiler. Die explizite native
Prüfung verlangt dagegen Binärhash und öffentlichen kompakten Quellbaum:

```bash
ADAPTIVE_SOLAR_RUST_MODULE="$(pwd)/artifacts/rust-quality-streaming-target/release/lib_archive_probe.so" \
ADAPTIVE_SOLAR_RUST_MODULE_SHA256="BINARY_SHA256" \
ADAPTIVE_SOLAR_QUALITY_SOURCE_ROOT="/ABSOLUTER/EINGEFRORENER/QUELLBAUM" \
.venv/bin/python -m pytest -q rust/archive_probe/tests/test_projection.py
```

Die Differentialtests des Originalreaders bleiben zusätzlich Pflicht. Für den
neuen Build einen neuen `CARGO_TARGET_DIR` benutzen und ältere gemessene
Binärdateien erhalten. Der [Phasenmesshelfer](performance-qualitaetsphasen.md)
aktiviert den neuen Arm ausdrücklich mit `--rust-projection` zusätzlich zu
`--rust-module PATH --rust-module-sha256 SHA256`. Alle anderen Offlinegrenzen
bleiben bestehen. `rust_projection` enthält Original-, Auswahl- und
Fallbackzähler sowie Quellen-, Query-, Policy- und Binärbindung. Der Aufwand
des nativen Quellscans liegt innerhalb der Ableitung; bei Phasenmessungen wird
auch die Iteratorerzeugung erfasst.

Vor der Messung Kriterien und Reihenfolge festhalten. Referenz für den
zusätzlichen Nutzen ist der bereits geprüfte Rust-Originalreader mit derselben
neuen Binärdatei, demselben Quellbaum und denselben eingefrorenen Eingaben.
Entscheidungen, Originalreferenzen, Konfigurationsnachweise, Rohcapture und
echte Verfügbarkeitschronologie müssen exakt übereinstimmen. Uninstrumentierte
ABBA-Läufe, CPU und Spitzen-RAM getrennt berichten; zwei Läufe pro Arm ergeben
keine belastbare p95. Mehr Geschwindigkeit allein genügt bei überschrittenem
Speicherkriterium nicht zur Abnahme. Hostdaten, Einzelzeiten und konkrete Abnahmekriterien
gehören unter ignorierte Betriebsdokumentation.

Ein beschleunigter eingefrorener Qualitätslauf belegt weder die Laufzeit eines
vollständigen produktiven Jobs noch höhere Prognosegüte. Die
[Diensttelemetrie](archiv-laufzeittelemetrie.md) untersucht Lock, Netzabruf,
Storeinitialisierung und übrige Jobphasen getrennt. Während einer solchen
Hostmessung keine zusätzliche Benchmarklast auf demselben Host erzeugen.
