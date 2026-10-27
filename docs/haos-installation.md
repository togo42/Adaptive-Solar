# HAOS: scikit-learn für Adaptive Solar bauen und installieren

Stand: 27.10.2026, Integrationsreferenz 0.2.12 (unveränderte Binärbasis seit 0.2.10). Bau-/Lieferweg seit Adaptive Solar **0.2.0**, kein anderes Lernmodell: normales CPython **3.14**, **amd64/x86_64**, **musllinux 1.2**. Andere ABIs/Architekturen, insbesondere ARM/Raspberry Pi, sind nicht geprüft. Einstieg und HACS: [Installation](installation.md). Historische Rohbelege bleiben privat; alle nötigen Bau-/Lieferbefehle stehen hier.

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

## 5. Lieferung in den persistenten Corepfad

Der Buildhelfer installiert nichts auf HA. Die folgenden Schritte führt der Betreiber
nach Prüfung seiner Plattform aus. Die dokumentierte native Installation ist von
dieser Anleitung und dem lokalen Paketierungstest zu unterscheiden.

### 5.1 Core und Sicherung prüfen

1. Tatsächlicher Core: CPython 3.14/amd64/Musl≥1.2. SSH-App ist ein anderer Interpreter.
2. Native NumPy/SciPy/Pandas unverändert gegen den Wheel prüfen, keine Buildvenv-Pakete nach `/config/deps` oder andere Corepfade kopieren.
3. Sicherung der HA-Konfiguration und jedes bereits vorhandenen Zielpakets erstellen.
   Fremde Pakete im gemeinsamen Abhängigkeitspfad gehören nicht zu diesem Payload.
4. Der hier beschriebene Pfad gilt für Core mit Konfigurationswurzel `/config` und
   normalem CPython 3.14: **`/config/deps/lib/python3.14/site-packages`**. Core ermittelt
   den User-Site-Pfad mit `PYTHONUSERBASE=<config>/deps` und stellt ihn vor die normalen
   Imports ([Core-Mount](https://github.com/home-assistant/core/blob/2026.10.4/homeassistant/bootstrap.py),
   [Pfadermittlung](https://github.com/home-assistant/core/blob/2026.10.4/homeassistant/util/package.py)).
   Vor Verwendung mit der tatsächlichen Coreversion abgleichen; keine Pythonversion
   aus einer SSH-App einsetzen. Bei anderer Wurzel/ABI diesen Weg nicht ungeprüft übernehmen.

### 5.2 Payload auf der Buildmaschine vorbereiten

Nach erfolgreichem Build und `SHA256SUMS`-Prüfung in Abschnitt 4 in ein neues Ziel
installieren. `wheel_work` bezeichnet weiterhin den in Abschnitt 2 erzeugten Ordner.
Diese reine Bereitstellung darf auch auf glibc laufen: `pip` wählt explizit die
Zielplattform, importiert aber keine Musl-Erweiterungen im Hostinterpreter.

```bash
python3 -m venv "$wheel_work/packaging-venv"
"$wheel_work/packaging-venv/bin/python" -m pip install \
  --no-index --no-deps --no-compile --only-binary=:all: \
  --platform musllinux_1_2_x86_64 --implementation cp --python-version 3.14 --abi cp314 \
  --find-links "$wheel_work/result/repaired" --find-links "$wheel_work/result/runtime" \
  --target "$wheel_work/deps-payload" \
  scikit-learn==1.9.1 joblib==1.6.0 narwhals==2.27.1 threadpoolctl==3.7.0 cloudpickle==3.1.2
```

Nur diese fünf Distributionen einschließlich `scikit_learn.libs` und aller
`.dist-info`-Ordner ausliefern. Keine NumPy-/SciPy-/Pandas-Verzeichnisse aus der
Buildvenv übernehmen. Die Lizenzdateien der Distributionen bleiben enthalten.
Die [pip-Zieloptionen](https://pip.pypa.io/en/stable/cli/pip_install/) ermöglichen
Plattformauswahl; `--no-index`/`--no-deps` verhindern einen neuen freien Resolverlauf.
Das Ziel muss vor dem Befehl unbenutzt sein; kein `--upgrade` in fremde Pakete hinein.

### 5.3 Kopieren, Neustart und Rückweg

Über einen bereits eingerichteten lokalen Dateizugang zur HA-Konfiguration arbeiten,
etwa Samba oder eine Dateiverwaltungs-App. Deren Mount kann anders heißen; entscheidend
ist die Konfigurationswurzel mit `configuration.yaml`, die im Core `/config` ist.

1. Core nach abgeschlossener Sicherung über eine vorhandene Supervisor-Konsole mit
   `ha core stop` stoppen. Der für den
   Transfer verwendete Dateizugang muss unabhängig von Core weiterlaufen.
2. Innerhalb dieser Wurzel `deps/lib/python3.14/site-packages` bereitstellen.
   Bereits vorhandene Versionen der fünf Payloaddistributionen samt zugehörigen
   Metadaten und `.libs` außerhalb des aktiven Importpfads sichern. Ein bloßes
   Überkopieren über eine alte Paketversion kann gemischte Dateien zurücklassen.
3. Den **Inhalt** von `deps-payload` vollständig in diesen Zielordner kopieren.
   Nicht den gesamten gemeinsamen `site-packages`-Ordner ersetzen und nicht nur
   `.whl`-Dateien ablegen. Übertragene Dateien mit dem lokalen Payload byteweise
   bzw. anhand eigener SHA256-Dateilisten vergleichen; keine Geheimnisse exportieren.
4. Core mit `ha core start` wieder starten und Protokolle prüfen. Anschließend
   [Integrationsinstallation](installation.md#3-über-hacs-installieren) abschließen.

Bei einem fehlgeschlagenen Import Core wieder stoppen, ausschließlich die gelieferten
fünf Distributionen/zugehörigen Dateien entfernen und deren gesicherten Vorgänger
wiederherstellen. Danach starten und erneut prüfen. Nicht `deps` als Ganzes löschen.
Fehlt ein gesicherter Vorgänger, ist der Rückweg die Entfernung genau des neuen
Payloads; er stellt keine vorher nie vorhandene Integrationsfunktion her.

### 5.4 Im tatsächlichen Core prüfen

Versionen, Importpfade, Konfigurationsprüfung, Reparaturen und nativen Einrichtungsdialog
prüfen. Wer bereits einen administrativen Zugang zum **HAOS-Host** besitzt, kann
im laufenden Corecontainer folgende lokale Probe ausführen. Sie ist keine Aufforderung,
für die Installation einen neuen ungeschützten Debugzugang einzurichten; eine
SSH-App ohne Zugriff auf diesen Container ist kein gleichwertiger Ausführungsort.

```bash
docker exec -i homeassistant python3 - <<'PY'
from importlib.metadata import version
import sys

sys.path.insert(0, "/config/deps/lib/python3.14/site-packages")
import numpy
import scipy
import pandas
import sklearn
from sklearn.ensemble import GradientBoostingRegressor

assert sys.version_info[:2] == (3, 14)
assert version("scikit-learn") == "1.9.1"
assert sklearn.__file__.startswith("/config/deps/lib/python3.14/site-packages/")
for module in (numpy, scipy, pandas):
    assert not module.__file__.startswith("/config/deps/"), module.__name__
    print(module.__name__, module.__version__, module.__file__)
model = GradientBoostingRegressor(random_state=0).fit([[0.0], [1.0], [2.0]], [0.0, 1.0, 2.0])
assert len(model.predict([[1.5]])) == 1
print("sklearn", sklearn.__version__, sklearn.__file__, "synthetic fit/predict passed")
PY
```

Der neue Pythonprozess bildet die von Core gemountete User-Site explizit nach;
zusätzlich muss der **regulär geladene HA-Eintrag** nach Neustart funktionieren.
Die kleine Probe prüft native Imports und synthetisches Fit/Predict, kein produktives
Lernen. Ein Setupdialog allein prüft nicht alle ML-Erweiterungen. Reale Quellenqualität
und der spätere Prognosevergleich bleiben die Nachweise in Abschnitt 6.

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
