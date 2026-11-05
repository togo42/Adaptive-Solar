# ML-Runtime-Deliverybundle

Stand: 05.11.2026. Vorschau-Dependencytag: **`v0.2.23-runtime.1`**.
Lokale Paketierung ist keine Veröffentlichung oder produktive Installationsfreigabe.

## Zweck und Grenzen

`scripts/build_ml_runtime.py` erzeugt einen standardisierten
[PEP-517-Sdist](https://peps.python.org/pep-0517/#source-distributions), der **nicht
der Originalquellcode von scikit-learn** ist: Sein Backend liefert ausschließlich
den bereits gebauten, unveränderten, SHA256-gebundenen Musl-Wheel aus. Der
Distributionsname bleibt `scikit-learn`, die Version **1.9.1**. Das neue
Dependencytag versioniert die Lieferung, nicht das Lernmodell.

Nur normaler CPython 3.14, Linux x86_64, 64 Bit, Musl ≥1.2 wird für die
Wheel-Erzeugung akzeptiert. Kein ARM, PyPy, Windows, macOS, glibc, `cp314t` oder
Cross-Targeting. Das Backend liest SOABI **und den ELF-Interpreter des tatsächlich
laufenden Python**; nur dessen Musl-Loader darf mit einem festen Befehl und
fünf Sekunden Zeitlimit seine Version melden. Nicht nachweisbare Plattformen
werden vor dem ersten Ausgabeschreiben abgelehnt. Frontend-Zieloptionen oder
`config_settings` überschreiben diese Prüfung nicht.

Die Integration lässt die Installation bei lokal fehlendem sklearn über die
offizielle HA-Funktion `async_process_requirements` erledigen. glibc verwendet
das normale PyPI-Requirement `scikit-learn==1.9.1`, **keinen hier verteilten
glibc-Wheel**. Bereits lokal vorhandenes sklearn wird durch das Bundle nicht
umgeschrieben. Dieses Dokument beschreibt das Lieferformat, nicht eine neue
Erlaubnis zum Ändern von Core, HA-Konfiguration oder Hostpaketen. Den aktuellen
Integrationsablauf beschreibt [Installation](../anwendung/installation.md).

## Feste Eingaben und Releaseassets

| Material | Identität / SHA256 |
| --- | --- |
| Musl-Wheel | `scikit_learn-1.9.1-cp314-cp314-musllinux_1_2_x86_64.whl` |
| Wheel-SHA256 | `7996d012c4aa741cc6386bbc107dec42e53f61ac39c4030362085f20df9293cf` |
| Originaler PyPI-Sdist | `629cada3e33e2b9bf376cdc7614a47a4140b8aedc1d836579e359736fbd82977` |
| GCC 15.2.0, vollständiger tar.xz | `438fd996826b0c82485a29da03a72d71d6e3541a83ec702df4271f6fe025d24e` |
| Alpine GCC-Paketversion | `15.2.0-r5` |
| aports-Commit | `423a8ad043d07f2c7546c8ec3e2b0384cda360ae` |

Der Builder ist das offizielle Image
`ghcr.io/home-assistant/wheels/amd64/musllinux_1_2/cp314:2026.10.0@sha256:65b0dfb84c7b8326fca5aa47df1f8e787f4903393f050266d2ba0c15850fd390`.
Der vorhandene Wheel-Bauweg mit Compilerpins und generischen CPU-Flags steht in
[HAOS-Wheel-Bau](../anwendung/haos-installation.md#2-ausschließlich-im-offiziellen-builder-ausführen)
und `scripts/build_haos_wheel.py`. Ein neuer Compilerlauf muss nicht bytegleich
sein. Weicht dessen Wheel-Hash ab, verweigert dieser Deliverybuilder die
Verwendung; Pins niemals allein zum Bestehen der Prüfung umstellen.

Ein vollständiger Dependencyrelease umfasst gemeinsam:

| Asset | Inhalt |
| --- | --- |
| `scikit_learn-1.9.1.tar.gz` | Rund 10 MB großer PEP-517-Delivery-Sdist mit genau einem unveränderten Musl-Wheel |
| `scikit_learn-1.9.1-original-source.tar.gz` | Vollständiger originaler PyPI-Sdist, nur zur Unterscheidung umbenannt |
| `gcc-15.2.0.tar.xz` | Vollständiger, unveränderter GCC-Upstreamquellcode |
| `gcc-15.2.0-r5-alpine-sources.tar.gz` | Exakter APKBUILD, alle **44** Alpine-Patches, Quelleninventar und Bauhinweise |
| `provenance.json` | Builder-/Paketidentitäten, Original-/Wheelbibliothekshashes und Quellasset-Hashes |
| `SHA256SUMS` | SHA256 aller fünf anderen Releaseassets |

Die Downloadbasis ist
`https://github.com/togo42/Adaptive-Solar/releases/download/v0.2.23-runtime.1/`.
Das Skript erzeugt nur lokale Assets, keine Uploads. Die Links in
`README.txt`/`NOTICE.txt` sind dauerhafte **Publikationsziele**, kein Nachweis,
dass die Assets bereits öffentlich erreichbar sind. Veröffentlichung erst nach
Prüfung des gesamten Satzes; alle Assets unter diesem Dependencytag unverändert
zusammen verfügbar halten, auch bei Spiegelung. Der original benannte
`scikit_learn-1.9.1.tar.gz` ist hier der Delivery-Sdist und darf nicht mit dem
Upstreamquellarchiv verwechselt werden.

## Öffentlicher Bauweg ohne private Dateien

Aus einem öffentlichen Checkout arbeiten, mit einer lokalen Python-Venv wie in
[Entwicklung](../entwicklung/entwicklung.md). Keine HA-Verzeichnisse oder
Zugangsdaten mounten. Die Paketierung selbst benötigt nur die Standardbibliothek,
keinen Compiler und kein Netzwerk.

### Quellen bereitstellen

Die Quellen lassen sich unabhängig von einer Betreiberinstallation von den
öffentlichen Ursprüngen beziehen. Folgendes Beispiel schreibt ausschließlich in
einen **neuen** lokalen Ordner und prüft SHA256/SHA512 gegen die im Checkout
enthaltenen Quellenrecords. Es ist eine bewusste Downloadvorbereitung, nicht Teil
des Installationsbackends:

```bash
mkdir -p artifacts
.venv/bin/python - <<'PY'
from hashlib import sha256, sha512
import json
from pathlib import Path
from urllib.request import urlopen

destination = Path("artifacts/ml-runtime-public-inputs")
destination.mkdir()  # Existierende Dateien nicht überschreiben.
records = json.loads(Path("tools/ml_runtime/source-records.json").read_bytes())
provenance = json.loads(Path("tools/ml_runtime/provenance.json").read_bytes())
rows = list(records["files"])
commit = records["aports_commit"]
rows.append({
    "filename": "APKBUILD",
    "url": f"https://raw.githubusercontent.com/alpinelinux/aports/{commit}/main/gcc/APKBUILD",
    "sha256": records["recipe_sha256"],
})
rows.append({
    "filename": "scikit_learn-1.9.1-original-source.tar.gz",
    "url": provenance["scikit_learn"]["source_url"],
    "sha256": provenance["scikit_learn"]["source_sha256"],
})
for row in rows:
    with urlopen(row["url"], timeout=30) as response:
        data = response.read(128 * 1024 * 1024 + 1)
    assert len(data) <= 128 * 1024 * 1024, row["filename"]
    assert sha256(data).hexdigest() == row["sha256"], row["filename"]
    if "sha512" in row:
        assert sha512(data).hexdigest() == row["sha512"], row["filename"]
        assert len(data) == row["size"], row["filename"]
    with (destination / row["filename"]).open("xb") as output:
        output.write(data)
PY
```

Die Dateinamen und URLs im versionierten `source-records.json` sind die festen
öffentlichen Quellen, keine frei aus einem Download übernommenen Befehle. Der
Deliverybuilder prüft zusätzlich den festen Hash dieses Records, den APKBUILD-Hash
und die vollständige Übereinstimmung seiner 45 SHA512-Einträge mit dem Inventar.
GCC plus alle Patches und das Rezept sind enthalten; nicht nur ein Patchauszug.

### Den geprüften Wheel beziehen

Vor Erstveröffentlichung stammt er aus dem separat geprüften öffentlichen
[Wheel-Bauweg](../anwendung/haos-installation.md#2-ausschließlich-im-offiziellen-builder-ausführen).
Nach Veröffentlichung kann derselbe Wheel ohne private Betreiberdateien aus dem
veröffentlichten Delivery-Sdist bezogen werden: zuerst dessen vollständigen
SHA256 gegen die hashgebundene URL in
`custom_components/adaptive_solar/runtime_requirements.json` prüfen, dann nur
`scikit_learn-1.9.1/wheels/scikit_learn-1.9.1-cp314-cp314-musllinux_1_2_x86_64.whl`
mit `tarfile.extractfile` in eine neue lokale Datei kopieren und gegen den obigen
Wheel-SHA256 prüfen. Keine unkontrollierte Archivextraktion verwenden. Der
Deliverybuilder prüft diese Identität erneut; ein zufälliger neuer Build oder
ein ähnlich benannter Fremdwheel wird nicht akzeptiert.

### Releaseassets lokal erstellen

Die Wheel-Variable zeigt ausdrücklich auf die zuvor geprüfte Datei. Die
Quellenpfade sind die oben öffentlich beschafften Materialien, keine privaten
Arbeitsverzeichnisse:

```bash
wheel=/pfad/zum/geprüften/scikit_learn-1.9.1-cp314-cp314-musllinux_1_2_x86_64.whl
.venv/bin/python scripts/build_ml_runtime.py \
  --wheel "$wheel" \
  --sklearn-source artifacts/ml-runtime-public-inputs/scikit_learn-1.9.1-original-source.tar.gz \
  --gcc-sources artifacts/ml-runtime-public-inputs \
  --output artifacts/ml-runtime-public-release
(cd artifacts/ml-runtime-public-release && sha256sum --check SHA256SUMS)
```

`--output` muss ein frischer direkter Unterordner von `artifacts/` dieses Checkouts
sein. Vorhandene Ziele und Symlinkpfade werden abgelehnt. Alle Eingabedateien,
Wheel-Metadaten, GCC-Lizenztexte und Quellhashes werden geprüft, **bevor** der
Ausgabeordner angelegt wird. Gleiches öffentliches Backend, Materialien und
Eingabebytes ergeben bei gleicher Python-/zlib-Implementierung dieselben Assets.
Kein Zeitstempel, privater Eingabepfad oder Hostname geht in die Assetbytes ein.
Unterschiedliche Kompressorversionen können andere gzip-Bytes erzeugen.

## Backendvertrag und Sicherheitsgrenzen

Das enthaltene `pyproject.toml` erklärt `requires = []`, `build-backend = "backend"`
und `backend-path = ["."]`. Alle PEP-517-Buildanforderungshooks liefern `[]`.
Keine Downloads, pip-Aufrufe, Compiler oder sklearn-Imports im Backend.

`prepare_metadata_for_build_wheel` authentifiziert den ganzen Wheel und schreibt
nur dessen geprüften `.dist-info`-Inhalt in einen neuen Ordner. `build_wheel`
vergleicht bei übergebenem `metadata_directory` sämtliche vorbereiteten
Metadatendateien bytegleich und liefert exakt die vorher authentifizierten
Wheelbytes; kein Entpacken, Reparieren oder Neubündeln. Zusätzliche, fehlende,
veränderte oder verlinkte Metadatendateien führen vor dem Wheel-Schreiben zum
Abbruch. `metadata_directory` ist gemäß PEP 517 der `.dist-info`-Ordner selbst.

`build_sdist` ist ein plattformneutraler Maintainerhook, kein Cross-Wheel-Build:
Er prüft das vollständige Payloadinventar, den fest gepinnten Wheel, `PKG-INFO`
und die Buildkonfiguration und schreibt einen PAX-tar.gz mit genau einer
`scikit_learn-1.9.1/`-Wurzel. Inhalte/Reihenfolge, Eigentümer, Dateimodi und
Zeitstempel sind normalisiert; gzip enthält weder Dateinamen noch Bauzeit.
Lizenzen und Herkunftsbeigaben bleiben Bestandteil des Inventars. Normale
Frontend-Caches neben dem Inventar gehören nicht zum Payload.

Grenzen: Wheel ≤32 MiB, entpackte ZIP-Inhalte ≤512 MiB und ≤50.000 Einträge,
Metadatendatei ≤2 MiB, gesamte Metadaten ≤8 MiB und ≤256 Dateien/Unterordner;
Delivery-Payload ≤64 MiB und ≤256 Inventardateien. Archivpfade sind auf 1.024
UTF-8-Bytes, 32 Segmente und 255 Bytes je Segment begrenzt.
Hashfehler, mehrdeutige `.dist-info`-Identitäten,
Pfadtraversal, ZIP-Duplikate, Datei-/Ordnerkollisionen, Sonderdateien und Symlinks
werden vor dem ersten Hook-Ausgabeschreiben abgelehnt. Die Kontrolle schützt
vor fehlerhaften Eingaben; sie ist keine Sandbox gegen gleichzeitige feindliche
Änderungen am Buildarbeitsverzeichnis. Der veröffentlichte Sdist selbst benötigt
einen von außerhalb des Archivs vertrauten SHA256; ein internes Manifest ist
keine Signatur und authentifiziert sich nicht selbst.

## Lizenzen, Quellen und Nachweise

Der unveränderte Wheel enthält scikit-learns BSD-3-Clause-COPYING sowie die
vendorten Array-API-Lizenztexte. Die Lieferung ergänzt die vollständigen
GCC-Texte `COPYING`, `COPYING3`, `COPYING.LIB`, `COPYING3.LIB`, `COPYING.RUNTIME`;
der Backendcode ist GPL-3.0-only. GCC-Runtimebedingungen und Runtime Exception
sind getrennt von scikit-learns Lizenz zu lesen. Der kompakte Delivery-Sdist
ersetzt weder den vollständigen GCC-Quellasset noch das Alpine-Rezeptarchiv.

`provenance.json` dokumentiert für libgcc, libgomp und libstdc++ die Version
15.2.0-r5 sowie vollständige SHA256 der Builderoriginale und der reparierten
Wheelbibliotheken. Die auditwheel-Namensprefixe `5ea51dd8`, `6c4ee807`, `67a94019`
passen zu den Originalhashes; nach auditwheel-Reparatur sind die ELF-Bytes anders.
Die APK-Datenbank des gepinnten Builders und dessen im Wheel erhaltener
auditwheel-6.8.2-SBOM bilden die dokumentierte Herkunft. Das ist keine pauschale
juristische Freigabe und kein Nachweis reproduzierbarer Compilerresultate.

Offlineprüfung:

```bash
.venv/bin/python -m pytest -q tests/test_ml_runtime_bundle.py
.venv/bin/ruff check tools/ml_runtime/backend.py scripts/build_ml_runtime.py tests/test_ml_runtime_bundle.py
```

Die Tests verwenden synthetische Wheel-/GCC-Quellen, prüfen beobachtbare
Abbrüche ohne Ausgaben, Metadatengleichheit, Plattform-/ELF-Gates,
deterministische Archive, vollständige Quellbeigaben und SHA256SUMS.
Keine Downloads und kein Compiler in Unittests. Lokale Paketierung und
simulierte Plattformtests belegen **keinen nativen erfolgreichen HA-Import,
Fit/Predict, produktiven Updatepfad oder Prognosevorteil**. Diese Nachweise sind
vor einer produktiven Veröffentlichung gesondert zu erbringen.
