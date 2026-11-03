# Optionaler Rust-Prototyp für Originalvalidierung

Dieser CPython-Hosthelfer ist ein lokaler Messkandidat. Er ist keine
Pflichtabhängigkeit der HA-Integration und wird nicht automatisch aktiviert.
Build, API, Differentialtests und Hostmessung beschreibt die
[Probeanleitung](../../docs/entwicklung/performance-rust-probe.md).

## Bauen

Eine ausdrücklich bereitgestellte Rust-Toolchain und der zum Test passende
CPython-Interpreter sind erforderlich. Das folgende Beispiel verwendet eine
bereits isoliert eingerichtete Toolchain; es installiert nichts:

```bash
env \
    CARGO_HOME="$PWD/artifacts/rust-toolchain/cargo" \
    RUSTUP_HOME="$PWD/artifacts/rust-toolchain/rustup" \
    CARGO_TARGET_DIR="$PWD/artifacts/rust-archive-target" \
    PYO3_PYTHON=/absolute/path/to/python3.14 \
    PATH="$PWD/artifacts/rust-toolchain/cargo/bin:$PATH" \
    cargo build --locked --release --manifest-path rust/archive_probe/Cargo.toml
```

Die Linux-Ausgabe ist
`artifacts/rust-archive-target/release/lib_archive_probe.so` mit dem
Python-Modulnamen `_archive_probe`. Das Modul verwendet die konkrete
CPython-ABI, nicht die Limited API; Interpreter, Architektur, Bibliotheken,
Buildumgebung und Binärhash müssen vor einem anderen Testhost geprüft werden.
Cargo-Abhängigkeiten sind in `Cargo.lock` gebunden. Der Build verwendet weder
`target-cpu=native` noch einen eingebauten produktiven Archivpfad.

## API und Fallback

```python
raw = _archive_probe.read_original(
    path,
    max_page_bytes,
    max_event_bytes,
    max_page_events,
    max_depth=64,
)
```

Ein Erfolg liefert die **unveränderten dekomprimierten Originalbytes** nach
vollständiger Prüfung. `None` verlangt den vollständigen nativen Pythonpfad,
der auch alle autoritativen Archivfehler erzeugt. Numerische Kanonisierung
verwendet die C-API des laufenden CPython statt einer Rust-Floatdarstellung.
Die unterstützte Teilmenge und ihre Grenzen stehen in der Probeanleitung.
Der Adapter muss auch ausreichenden Python-Aufrufstack-Headroom schützen.

Der Kern benötigt den GIL. Anschließend erzeugt der Adapter weiterhin den
normalen Pythonbaum mit `json.loads(raw)`; Queryprojektion und vermiedene
Pythonbaumerzeugung sind hier nicht umgesetzt.

## Prüfen

Die echte Binär-Differentialprüfung ist bewusst getrennt von der gewöhnlichen
Python-Testauswahl. Sie muss mit einem explizit gebundenen Modul laufen:

```bash
ADAPTIVE_SOLAR_RUST_MODULE="$PWD/artifacts/rust-archive-target/release/lib_archive_probe.so" \
ADAPTIVE_SOLAR_RUST_MODULE_SHA256=EXACT_BINARY_SHA256 \
    /absolute/path/to/python3.14 -m pytest -q rust/archive_probe/tests/test_differential.py
```

Fehlende Binärpins sind ein Fehler und kein erfolgreicher oder übersprungener
Rustnachweis. Erst ein vollständiger Vergleich einschließlich Adapterkosten
kann einen lokalen Geschwindigkeitsvorteil belegen.
