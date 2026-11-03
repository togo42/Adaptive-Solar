# Optionalen Rust-Originalreader differenziell prüfen

Stand: 03.11.2026. Separater Entwicklungsversuch für eine eingefrorene
Archivkopie. Der Helfer ist keine Abhängigkeit der HA-Integration und wird
weder vom Archivdienst noch von dessen Installer automatisch aktiviert.
Der gebundene lokale Vergleich und ein isolierter Hosttest erfüllen die vorab
festgelegten Entwicklungskriterien. Original-/Ergebnisparität und die
Binär-/Quellenbindung wurden unabhängig nachgelesen. Die konkreten Laufzeiten
und Hostzustände bleiben in der privaten Betriebsdokumentation.

## 1. Umfang und Semantik

[`rust/archive_probe`](../../rust/archive_probe/Cargo.toml) baut eine optionale
CPython-Erweiterung. Ihr erster Kern übernimmt das begrenzte Originallesen:
Gzip einschließlich verketteter Member, Dateihash, Wrapper, Seite, Envelopehash,
kanonische Bytegrößen, Schema, UUIDs, Sequenzen, Cursor und Lücken. Erfolgreich
geprüfte Originale kommen als **unveränderte dekomprimierte Bytes** zurück.
Die Python-Anbindung dekodiert diese mit `json.loads`; Ereignisselektion,
Payloadreferenzen, Quellen-/Generationsgegenbelege, Qualitätsgates und echte
Verfügbarkeitszeiten bleiben beim bisherigen Verbraucher.

Das ist zunächst eine Portierung der Validierungsschleifen. Es gibt noch keine
native Queryprojektion, die alle irrelevanten Pythonobjekte vermeidet. Jedes
vom nativen Quellscan verbrauchte Original wird in jedem Lauf neu geprüft;
ein früherer Planaufbau oder Validierungscache gehört nicht zu diesem Versuch.

Serde verarbeitet JSON mit `arbitrary_precision`. Die tatsächliche
Integer-/Floatkonversion und Zahlenformatierung verwenden CPython-C-APIs,
einschließlich aktiver Integer-Zifferngrenzen. Die unterstützte Teilmenge ist
konservativ: beispielsweise ASCII-Metadaten, übliche UTC-Zeitstempel und höchstens
64 geschachtelte JSON-Container. Doppelte Schlüssel, reservierte
Serde-Zahlenschlüssel, andere Zeitformen, tiefe Strukturen und alle unklaren
oder fehlerhaften Eingaben liefern keinen schnellen Erfolg.

In diesen Fällen führt der Adapter den vollständigen ursprünglichen
Pythonreader aus. Damit bleibt dessen Annahme-/Ablehnungsverhalten maßgeblich.
Ein normaler zusätzlicher Python-Wrapper würde die Rekursionsgrenze verschieben.
Deshalb fügt die Anbindung nur einen überprüften AST-Vorspann in die vorhandene
Readerfunktion ein; nach dessen Rückkehr läuft der unveränderte Nativebody im
selben Aufrufrahmen. Bei wenig Rekursionsspielraum wird der Rustpfad ausgelassen.

## 2. Bindung und Build

Der Versuch ist auf CPython 3.14 und ausdrücklich qualifizierte
`core/archive.py`-Dateihashes begrenzt. Andere Readerstände führen vollständig
über den Pythonpfad; eine Erweiterung der Liste erfordert einen neuen
Semantikabgleich. Schema 1, Runtimegrenzen, Binärhash, Protokoll und maximale
Tiefe werden geprüft. Ein geänderter Binär-, Adapter-, Reader- oder Runtimestand
während des Scopes verhindert einen erfolgreichen Abschluss.

Rust 1.90.0, die direkten Cargo-Versionen und `Cargo.lock` binden den Build.
Toolchain und Cratecache können außerhalb der normalen Installation unter
ignorierten Artefaktpfaden liegen. Beispiel nach Einrichtung dieser Toolchain:

```bash
PYO3_PYTHON="$(pwd)/.archive-venv/bin/python" \
CARGO_TARGET_DIR="$(pwd)/artifacts/rust-archive-target" \
cargo +1.90.0 build --locked --release --manifest-path rust/archive_probe/Cargo.toml
```

Interpreter, Compiler, Cargo, Lockdatei, Quellen und erzeugte Binärdatei mit
Versionen und SHA256 festhalten. Das Shared Object ist an die qualifizierte
CPython-ABI gebunden. Vor Nutzung auf einem anderen Host Architektur, Python-ABI
und erforderliche glibc-Versionen prüfen; dort muss keine Toolchain installiert
werden. Der Build und die Downloads verändern keine produktive Laufzeit.

## 3. Getrennte Tests

Die normale Python-Suite prüft Adapter, AST-Fallback, Hashbindung und
Lebenszyklus ohne Rust-Pflicht. Die echten Differentialtests werden zusätzlich
ausdrücklich mit dem gebauten Modul aufgerufen; ein fehlendes Modul ist dort
ein Fehler und kein übersprungener Test:

```bash
ADAPTIVE_SOLAR_RUST_MODULE="$(pwd)/artifacts/rust-archive-target/release/lib_archive_probe.so" \
ADAPTIVE_SOLAR_RUST_MODULE_SHA256="BINARY_SHA256" \
.venv/bin/python -m pytest -q rust/archive_probe/tests/test_differential.py
```

Diese Prüfung vergleicht Rawbytes, geparste Originale und Ablehnungen gegen
den gepinnten Pythonreader. Dazu gehören Zahlen einschließlich Exponenten,
negativer Null, Subnormalzahlen und großer Integer, Unicode, doppelte Schlüssel,
Surrogate, Encodingvarianten, beschädigtes Gzip, Hash-/Schema-/Größenfehler
sowie tiefe Bäume und knapper Rekursionsspielraum. Die vollständige
Qualitätsableitung wird zusätzlich mit Originalreferenzen und
Konfigurationsbelegen verglichen. Ein synthetischer Smoke allein genügt nicht.

## 4. Laufzeit und Hostprobe

Der [Phasenmesshelfer](performance-qualitaetsphasen.md) nimmt für einen eigenen
Versuchsarm `--rust-module PATH --rust-module-sha256 SHA256` an. Eine Kombination
mit dem eingefrorenen Auswahlplan ist absichtlich ausgeschlossen. Beide Arme
verwenden dieselben Quellen, Originale, Rohcapture, Policy und denselben
HA-freien Interpreter. Binär-/Sourceprüfung, Modulimport, AST-Kontextaufbau und
abschließende Pinhashes sind in der äußeren Workerzeit erfasst; die innere Laufzeit umfasst die gesamte Ableitung
einschließlich Rustlesen, Pythondekodierung und aller tatsächlichen Fallbacks.

`rust_probe` berichtet schnelle Originale, native Fallbacks und deren Gründe,
geschlossenen Scope, Runtime- und Binärpins sowie AST-/Codehashes. Null schnelle
Originale sind kein Rust-Geschwindigkeitsnachweis. Inklusive Phasenzeiten
überlappen weiterhin; die uninstrumentierten ABBA-Läufe liefern den Vergleich.

Für einen Hosttest ausschließlich einen neuen, gehashten Testbereich nutzen.
Hostidentität und ABI vor Übertragung lesend bestätigen. Öffentliche Testquellen,
das geprüfte Modul und die unveränderten eingefrorenen Eingaben hashen,
übertragen und am Ziel nachlesen. Der Test verändert keine Dienst-/Timerkonfiguration,
Releasepfade, Credentials oder produktiven Originale. Während der Probe
laufende Dienste und Hostlast dokumentieren; daraus keine Messung bei ruhendem
Host ableiten. Reguläre Jobs können ihren Zustand ändern oder fehlschlagen;
solche Befunde getrennt prüfen und offen berichten. Eine Beteiligung der
Benchmarklast lässt sich nicht allein aus der zeitlichen Überlappung beweisen
oder ausschließen. Worker erhalten keine HA-Zugangsdaten und blockieren HA-Imports
und Netzwerkzugriffe. Originale und Vergleichsausgaben bleiben privat.

Die konkreten Host-, Datei-, Einzelzeit- und Integritätsbelege gehören unter
ignorierte Betriebsdokumentation. Eine gemessene lokale oder isolierte
Hostbeschleunigung aktiviert den Helfer nicht im laufenden Archivbetrieb.
Sie ist auch keine Wiederholung eines vollständigen produktiven Archivjobs:
Netzwerk, Writerlock, Storeinitialisierung und dessen übrige Aufgaben liegen
außerhalb dieser eingefrorenen Qualitätsableitung.
