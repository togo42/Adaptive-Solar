# HAOS: scikit-learn-Wheel für Adaptive Solar bauen und prüfen

Stand: 25.10.2026. Bau-/Lieferweg seit Adaptive Solar **0.2.0**, kein anderes Lernmodell: normales CPython **3.14**, **amd64/x86_64**, **musllinux 1.2**. Andere ABIs/Architekturen sind nicht geprüft. Vollständiger Vorgänger im lokalen, unveröffentlichten Archiv `artifacts/releases/0.2.5-blocked/source/docs/haos-installation.md`.

## 1. Anlass und feste Eingaben

Für `scikit-learn==1.9.1` fehlte der passende fertige HA-Musl-Wheel. [build_haos_wheel.py](../scripts/build_haos_wheel.py) baut dieselbe Version aus unverändertem PyPI-Sdist; glibc-Wheels ersetzen dies nicht. [Offizielle HA-Builderfamilie](https://github.com/home-assistant/wheels), fester Aufruf:

```text
ghcr.io/home-assistant/wheels/amd64/musllinux_1_2/cp314:2026.10.0@sha256:65b0dfb84c7b8326fca5aa47df1f8e787f4903393f050266d2ba0c15850fd390
```

[PyPI-Sdist 1.9.1](https://pypi.org/project/scikit-learn/1.9.1/#files): `scikit_learn-1.9.1.tar.gz`, SHA256:

```text
629cada3e33e2b9bf376cdc7614a47a4140b8aedc1d836579e359736fbd82977
```

| Isolierter Buildpin | Version |
| --- | --- |
| NumPy | 2.3.2 |
| SciPy | 1.18.1 |
| Cython | 3.2.5 |
| meson-python | 0.21.0 |
| ninja | 1.13.2 |

Diese Compilerumgebung ersetzt keine nativen Corepakete. Weitere aufgelöste Abhängigkeiten/Werkzeuge werden protokolliert; gleiche Eingaben garantieren keine bitidentischen Compilerresultate.

## 2. Ausschließlich im offiziellen Builder ausführen

Buildmaschine mit Docker, PyPI-Zugang und Platz für eine frische Venv; Helfer ohne Rootbedarf. Vom Repository aus nur öffentliche Helferdatei und neuen Arbeitsordner mounten, weder HA-Core noch Konfiguration/Zugangsdaten:

```bash
mkdir -p artifacts
wheel_work=$(mktemp -d "$PWD/artifacts/adaptive-solar-haos-wheel.XXXXXX")
docker run --rm --platform linux/amd64 \
  --user "$(id -u):$(id -g)" --workdir /work \
  --mount "type=bind,src=$PWD/scripts/build_haos_wheel.py,dst=/tools/build_haos_wheel.py,readonly" \
  --mount "type=bind,src=$wheel_work,dst=/work" --entrypoint python3 \
  ghcr.io/home-assistant/wheels/amd64/musllinux_1_2/cp314:2026.10.0@sha256:65b0dfb84c7b8326fca5aa47df1f8e787f4903393f050266d2ba0c15850fd390 \
  /tools/build_haos_wheel.py --output /work/result
```

Output muss neu sein; vorhandene Pfade/Symlinks werden abgelehnt. Vor Download/Schreiben prüft der Helfer CPython, ABI, Architektur, nicht-freethreaded Interpreter und Musl-Loader. WSL/glibc ist kein Buildinterpreter. Der Image-Digest wird extern gebunden; innerhalb des Containers kann der Helfer OCI-Identität nicht attestieren. Startbefehl/Exit bleiben Teil des Nachweises.

## 3. Ablauf des Helfers

Sdist herunterladen, **vor Buildausführung** hashen; isolierte Venv ohne Systempakete, fünf Buildpins, deren `bin` zuerst im `PATH` (auch Ninja). Arbeitsdaten liegen unter `artifacts/`, kein freies `/tmp` vorausgesetzt. Generische Flags `-O2 -march=x86-64 -mtune=generic`; geerbtes `-march=native`/`-ffast-math` wird nicht übernommen.

[Wheel-Build](https://pip.pypa.io/en/stable/cli/pip_wheel/):

```text
pip wheel --no-deps --no-build-isolation --config-settings=compile-args=-j2
```

Danach `auditwheel show`, `auditwheel repair --plat musllinux_1_2_x86_64`, erneut `show`. [auditwheel](https://github.com/pypa/auditwheel) bündelt ELF-Laufzeitbibliotheken; Referenz: `libgcc_s`, `libgomp`, `libstdc++`, tatsächliche Liste im Manifest. Erfolg erfordert reparierten `cp314-cp314-musllinux_1_2_x86_64`-Wheel und eindeutigen Auditbericht ohne externe Shared Libraries.

Pro Unterprozess standardmäßig 3600 s, `--timeout` höchstens 7200 s. Fehler/Timeout bleibt `status: failed`, kein Erfolgsnachweis. Kein Deploy/produktiver HAOS-Build.

## 4. Ergebnis und reine Python-Laufzeitabhängigkeiten

| Bereich | Inhalt |
| --- | --- |
| `src/` | Originaler gehashter Sdist |
| `raw/` | Unreparierter Roh-Wheel, kein Installationspayload |
| `repaired/` | Reparierter Musl-scikit-learn-Wheel |
| `runtime/` | Nur vier reine Runtime-Wheels unten |
| `logs/`, `manifest.json`, `SHA256SUMS` | Befehle/Exits, Versionsstände, Artefakthashes |
| `build-venv/`, temporäre Baupfade | Buildzustand, kein Installationspayload |

Runtime: **joblib 1.6.0, narwhals 2.27.1, threadpoolctl 3.7.0, cloudpickle 3.1.2**. Joblib benötigt zusätzlich `cloudpickle>=3.0`. Download mit `--no-deps`, Prüfung auf `py3-none-any`; keine NumPy-/SciPy-/Pandas-Runtimewheels. Integrität:

```bash
(cd "$wheel_work/result" && sha256sum --check SHA256SUMS)
```

Nur `repaired/` plus vier `runtime/`-Wheels kommen für Installation infrage. Hashprüfung ist keine unabhängige Signatur/Modellgüteprüfung.

## 5. Voraussetzungen für eine HAOS-Installation

Separater konkret freigegebener Arbeitsschritt; der Helfer installiert nichts:

1. Tatsächlicher Core: CPython 3.14/amd64/Musl≥1.2. SSH-App ist ein anderer Interpreter.
2. Native NumPy/SciPy/Pandas unverändert gegen den Wheel prüfen, keine Buildvenv-Pakete nach `/config/deps` oder andere Corepfade kopieren.
3. Geprüfter persistenter Abhängigkeitspfad enthält vollständig entpackte Distributionen einschließlich `.libs`/`.dist-info`; abgelegte `.whl` allein genügt nicht. Kein unbeschränkter Resolver überdeckt Corepakete; der Pfad muss installationsspezifisch feststehen.
4. Nach erforderlichem Core-Neustart tatsächliche Paketversionen/-pfade, Config Check, Repairs, Integrationserkennung/nativen Dialog prüfen. Nachträgliche Abhängigkeiten können einen weiteren Neustart brauchen. Reinen Prüfdialog abbrechen; keine Anlageneinrichtung daraus ableiten.

## 6. Getrennte Nachweise

Build/Buildvenv-`pip check` belegen zunächst den Bauweg. Davon getrennt:

- **Musl-Testvenv:** Dependencycheck, HA-freie Kerntests, synthetische Learner-Parität zur Entwicklungsreferenz.
- **Nativer Core:** seine eigenen Imports und Fit/Predict. Metadaten, Setupform oder SSH-App-Fit ersetzen diesen Nachweis nicht.
- **Produktive Anlage:** qualifizierte Messintervalle und fairer [prospektiver Vergleich](validierung.md).

Der Helfer lässt `native_core_verified`, `model_fit_verified`, `synthetic_parity_verified` daher auf `false`; spätere Nachweise brauchen eigene Interpreter-/Versions-/Quell-/Wheelhashbindung.

## 7. Grenzen des neuen Helfers

24 Tests mit synthetischen Wheels/gemockten Werkzeugen prüfen Hash/Plattform/Output, Befehlsfolge, Flags/Metadaten und Audit; kein Download/Compiler/HA.

Historischer echter Helferlauf: rootless `bwrap` im gebundenen Builder, neun Befehle Exit0/sieben Artefakte; nicht der Docker-Aufruf. Separat bestand dessen Wheel Musl-`pip check`,134 Kerntests/144 synthetische Holdouts exakt gleich zur Entwicklung. Nachweise unter `artifacts/haos-wheel-build/`: `work/public-helper-proof/`, `work/public-helper-core-tests.xml`, `work/public-helper-parity-musl.json`, `public-helper-test.log`.

Helferflags bleiben false; der zuvor installierte gleichversionige Wheel besitzt eigene Hash-/Hostproben. [Aktuelle Kerntests](entwicklungsstand.md) ersetzen keinen nativen Core-Fit oder realen Prognosevergleich.
