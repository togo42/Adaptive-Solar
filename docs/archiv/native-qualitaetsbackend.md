# Optionales natives Qualitätsbackend auf dem Archivhost

Stand: 03.11.2026. Der Archivhost kann die vollständige Originalprüfung,
Auswahl und Konfigurationsprojektion der laufenden Qualitätsableitung an den
separat gebauten Rustkern übergeben. Der Pythonpfad bleibt Standard; HA Core
und HACS benötigen weder Rust noch eine neue Abhängigkeit. Die
[eingefrorenen Versuche](../entwicklung/performance-rust-projektion.md) und
eine konkrete produktive Installation sind getrennte Nachweise.

## Aktivierungsvertrag

[`native_quality_backend.py`](../../scripts/native_quality_backend.py) bindet
den neuen Pfad direkt in `continuous_quality.derive(..., backend=...)` ein.
Es gibt dabei keine globalen Funktionsersetzungen oder AST-Patches. Die
bisherigen Zeit-, Quellen-, Generations-, Konfigurations- und Qualitätsgates
bleiben erhalten. Originalreferenzen und die Arbeitsgröße vollständiger
Forecastenvelopes werden nicht durch abgeschnittene Ersatzoriginale ersetzt.

Das explizite Manifest `adaptive-solar-native-quality-runtime-v1` enthält:

- Projektionsprotokoll 2 und den kanonischen Releasepfad;
- neun feste Source-Dateihashes einschließlich Verbraucher, Archivreader und Backend;
- relativen Bibliothekspfad und SHA256;
- CPythonversion, ABI, GILmodus, Interpreter-Binärhash und fünf numerische Laufzeitversionen.

Reader und Python-Konfigurationsfabrik müssen zusätzlich ausdrücklich
qualifizierte Dateistände sein. Ein neu berechneter Manifesthash allein
qualifiziert keinen beliebigen neuen Verbraucher. Die unterstützte Laufzeit
ist CPython 3.14 mit GIL; ein anderer Stand benötigt eine neue Abnahme.

Bekannte Konfigurationsfehler wie falsche Quellen-, Runtime-, Manifest- oder
Binärpins beenden die angeforderte Aktivierung geschlossen. Sie werden nicht
als erfolgreich verwendeter Rustpfad gemeldet. Bei einer vom Kern nicht
unterstützten Datenform wird hingegen die **gesamte Quelle** mit dem
ursprünglichen Pythoniterator gelesen. Vorher wird kein Teilergebnis
veröffentlicht. Ausnahmen und Signale werden weitergereicht. Die bisherigen
512-MiB-/500.000-Ereignisbudgets gelten weiterhin; Anker außerhalb der
Bindungsperiode, andere Generationen und Payloadabhängigkeiten bleiben erhalten.

## Bauen und Manifest vorbereiten

Die Bibliothek separat mit Rust 1.90.0, `Cargo.lock`, `--locked --release` und
dem qualifizierten CPythoninterpreter bauen. Beispiel und Differentialtests
stehen im [Rust-Originalreaderversuch](../entwicklung/performance-rust-probe.md).
Binärdatei, Nativequellen, Toolchain und ABI hashen. Auf dem Archivhost werden
weder Compiler noch Pip-Pakete für diese Aktivierung installiert. Eine fremde
glibc-/Architekturbasis darf nicht ungeprüft übernommen werden.

Der Helfer erstellt nur ein Manifest, keine Installation:

```bash
python scripts/native_quality_manifest.py \
  --source-root /ABSOLUTER/GEPRUEFTER/QUELLBAUM \
  --release-root /home/USER/adaptive-solar-archive/releases/QUELLCOMMIT \
  --binary /ABSOLUTER/BUILD/lib_archive_probe.so \
  --runtime-json data/native-quality/runtime.json \
  --output data/native-quality/QUELLCOMMIT.json
```

`runtime.json` enthält genau die Felder `implementation`, `version`, `soabi`,
`gil_disabled`, `python_binary_sha256` und `dependencies` des Aktivierungsvertrags;
sie werden frisch aus dem bestehenden HA-freien Hostinterpreter gelesen.
Keine Umgebungswerte oder Zugangsdaten hineinkopieren. Der Helfer gibt den
externen Manifest-SHA256 aus und schreibt eine neue Datei mit Modus `0600`.
Er lädt die Bibliothek nicht und aktiviert keinen Dienst.

## Bestehende Installation aktivieren

Vorher den aktuellen Achtbindungsfall beziehungsweise den tatsächlichen
Installationsumfang unter dem bestehenden Writer-/Archivlock einfrieren.
Originale, Index, vollständige Policy und vorhandenes Capture einschließlich
seiner bisherigen Qualitäts-/Normalisierungsevidenz erhalten. Pythonreferenz
und Kandidat mit **demselben neuen Quellstand** vergleichen; echte neu
berechnete Zeitfelder getrennt von stabilen Fakten prüfen. Der ältere
Vierbindungsbenchmark ersetzt diese Abnahme nicht.

Nach Tests, Source-Review und Push eine neue unveränderliche Releasekopie
mit `native/lib_archive_probe.so` bereitstellen. Bestehende `.venv`- und
`data`-Links müssen exakt auf die vorgesehenen Laufzeit-/Datenziele zeigen.
Die Sourcekopie wird cachefrei übertragen und schreibgeschützt bereitgestellt;
Python-Bytecode-Schreiben bleibt in Eltern- und Kindprozessen deaktiviert.
`-B` allein verhindert nicht das Lesen eines bereits vorhandenen Bytecodecaches.
Keine alten `__pycache__`-Verzeichnisse in den neuen Release übernehmen.

Nur diese beiden Felder werden der privaten Hostkonfiguration hinzugefügt:

```json
{
  "quality_backend_manifest": "data/native-quality/QUELLCOMMIT.json",
  "quality_backend_manifest_sha256": "EXTERNER_MANIFEST_SHA256"
}
```

Beide Felder sind zusammen erforderlich, außerdem `quality_bindings` und eine
Actuals-Zuordnung. Der Runner reicht sie ausschließlich an `actuals` und den
kompatiblen kombinierten `observations`-Job weiter. `references`, HA-, Wetter-
und Retentionsaufgaben verwenden diese Auswahl nicht. Die CLI-Entsprechungen
heißen `--quality-backend-manifest` und `--quality-backend-manifest-sha256`.
Alle bisherigen privaten Konfigurationswerte und Zugangsdaten bleiben erhalten.

Vor dem atomaren `current`-Wechsel vorhandene Timerzustände sichern, die
betroffenen Timer vorübergehend stoppen und alle Schreiber auslaufen lassen.
Nicht deaktivieren und keinen laufenden Schreiber abbrechen. Ein kontrolliertes
Writerlockfenster verhindert eine Mischung alter und neuer `current`-Quellen
beim Pythonstart. Units, Kalender, Shared-venv und Archivlayout bleiben erhalten.
Danach genau einen kontrollierten regulären Actuals-Lauf durchführen und die
ursprünglichen Timerzustände wiederherstellen.

## Nachweis und Rückfall

`actuals.json` beziehungsweise der äußere Beobachtungsreport enthält den
begrenzten `quality_backend`-Nachweis: angefordert/effektiv, Protokoll,
Manifest-/Binär-/Quellenhash, geschlossener Scope, projizierte Quellen und
Original-/Auswahl-/Konfigurationszähler sowie feste Rückfallgründe. Die
abgeleiteten Capture-Daten und `quality_derivation` erhalten keine
backendabhängigen Zusatzfelder. Der Elternrunner übernimmt ausschließlich
validierte feste Labels, Hashes und nichtnegative Zähler aus der Kindausgabe.

Die Installationsabnahme verlangt Jobabschluss, erwartete Pins und tatsächliche
native Verwendung. Ein nur konfigurierter Pfad oder ausschließlich Python-
Rückfälle sind kein Beschleunigungsnachweis. Vollständige Originalprüfung und
normale Datenfehler bleiben wichtiger als ein schneller Erfolgsstatus.

Bei fehlgeschlagener Installationsabnahme den vorherigen `current`-Link, die
ursprünglichen Konfigurationsbytes und Timerzustände zurücksetzen. Keine
Originale, neuen Checkpoints oder Indexdateien aus einem älteren Snapshot
zurückkopieren. Ohne die beiden Aktivierungsfelder läuft wieder der reguläre
Pythonpfad. Die bestehende Host-/PBS-Sicherung bleibt ein eigener
Betriebsnachweis; für diesen Sourcewechsel wird kein paralleler Backupdienst
eingerichtet.

Regressionen stehen in `tests/test_native_quality_backend.py`,
`tests/test_native_quality_manifest.py`, `tests/test_archive_host.py` und
`tests/test_archive_observations.py`. Der reale Backendtest benötigt explizit
`ADAPTIVE_SOLAR_TEST_NATIVE_QUALITY_BINARY=/ABSOLUTER/PFAD/lib_archive_probe.so`;
ohne diese Variable bleibt nur dieser zusätzliche Realtest ausgesetzt.
Die CI baut das optionale Modul separat und setzt die Variable für die volle
Python-/HA-Suite; die zusätzlichen Native-Differentialtests laufen ebenfalls.
