# HAOS: scikit-learn für Adaptive Solar bauen und installieren

Stand: 05.11.2026, vorbereitete Integrationsreferenz 0.2.23 (unveränderte Binärbasis seit 0.2.10). Bau-/Lieferweg seit Adaptive Solar **0.2.0**, kein anderes Lernmodell: normales CPython **3.14**, **amd64/x86_64**, **musllinux 1.2**. Andere ABIs/Architekturen, insbesondere ARM/Raspberry Pi, sind nicht geprüft. Einstieg und Marketplace: [Installation](installation.md). Historische Rohbelege bleiben privat; alle nötigen Bau-/Lieferbefehle stehen hier.

**Ab 0.2.23 übernimmt der HA-native Bootstrap die Paketlieferung.** Betreiber
installieren die Integration über Marketplace; sie benötigen weder den folgenden
Compilerbau noch manuelle Docker-/SSH-Eingriffe. Der Bauweg in Abschnitten 1–4
bleibt für die Releasepflege relevant. Der
[Binärliefervertrag](../technik/ml-runtime-bundle.md) beschreibt die hashgebundene
Weitergabe einschließlich Quell- und Lizenzbeigaben. Die folgenden manuellen
Lieferanleitungen dokumentieren ältere Versionen und gezielte Wiederherstellung,
nicht die normale Marketplace-Installation ab 0.2.23.

**Wichtige Grenze ab Core 2026.11:** Der frühere Lieferpfad `/config/deps` wird
nicht mehr geladen. Abschnitte 5.1–5.4 beschreiben ausschließlich den historischen
Core-2026.10-Weg; für 2026.11 gilt [Abschnitt 5.5](#55-core-ab-202611-pakete-im-corecontainer).
Die Wheel-Bauparameter bleiben unverändert, solange die tatsächliche Core-ABI
weiterhin passt. Nicht den alten Pfad durch einen globalen `sys.path`- oder
`PYTHONPATH`-Eingriff wieder aktivieren.

## 1. Anlass und feste Eingaben

Für `scikit-learn==1.9.1` fehlte der passende fertige HA-Musl-Wheel. [build_haos_wheel.py](../../scripts/build_haos_wheel.py) baut dieselbe Version aus unverändertem PyPI-Sdist; glibc-Wheels ersetzen dies nicht. [Offizielle HA-Builderfamilie](https://github.com/home-assistant/wheels), fester Aufruf:

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

## 5. Versionsabhängige Lieferung in Core

Der Buildhelfer installiert nichts auf HA. Die folgenden Schritte führt der Betreiber
nach Prüfung seiner Plattform aus. Die dokumentierte native Installation ist von
dieser Anleitung und dem lokalen Paketierungstest zu unterscheiden.

### 5.1 Core bis 2026.10 und Sicherung prüfen

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

### 5.3 Core bis 2026.10: Kopieren, Neustart und Rückweg

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
   [Integrationsinstallation](installation.md#3-über-marketplace-installieren) abschließen.

Bei einem fehlgeschlagenen Import Core wieder stoppen, ausschließlich die gelieferten
fünf Distributionen/zugehörigen Dateien entfernen und deren gesicherten Vorgänger
wiederherstellen. Danach starten und erneut prüfen. Nicht `deps` als Ganzes löschen.
Fehlt ein gesicherter Vorgänger, ist der Rückweg die Entfernung genau des neuen
Payloads; er stellt keine vorher nie vorhandene Integrationsfunktion her.

### 5.4 Core bis 2026.10: Im tatsächlichen Core prüfen

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

### 5.5 Core ab 2026.11: Pakete im Corecontainer

Historischer manueller Reparaturweg für Adaptive Solar bis einschließlich
0.2.22. Ab 0.2.23 ist stattdessen die automatische Marketplace-/HA-Lieferung oben
vorgesehen. Dieser Abschnitt bleibt als begrenzter Diagnose- und Rückweg erhalten.

HA hat die Konfigurationsverzeichnis-Abhängigkeiten mit
[Core-Änderung #168155](https://github.com/home-assistant/core/pull/168155)
entfernt. Der [Paketinstaller von 2026.11.0](https://github.com/home-assistant/core/blob/2026.11.0/homeassistant/util/package.py)
installiert im Container regulär in dessen Pythonumgebung. Bereits vorhandene
Dateien unter `/config/deps` erfüllen deshalb den Requirementcheck nicht mehr.
Ohne passenden Wheel versucht HA einen Sdist-Bau; ein Fehler wie
`PermissionError: ... 'meson'` ist kein Anlass, Compiler oder Buildvenv in Core
zu installieren.

Der folgende **manuelle Wiederherstellungsweg** setzt einen ausdrücklich
genehmigten administrativen Dockerzugriff auf den HAOS-Host voraus. Eine normale
SSH-App ohne Corecontainerzugriff genügt nicht; ihren Interpreter nicht als Core
ausgeben. Ein vorübergehend genehmigter schwächerer App-Schutzmodus muss nach
der Arbeit wiederhergestellt und die App neu gestartet werden. Keine neuen
öffentlichen Debugports öffnen.

1. Konfigurationsbackup vorab abschließen; eine bewusst ausgeschlossene
   Recorder-Datenbank ist darin nicht wiederherstellbar. Die bestehenden
   ML-Paketdateien sowie Konfiguration, Entity-IDs und Lern-/Tagesstartdaten
   separat für den Vorher-/Nachhervergleich erhalten; keine `.storage`-Dateien
   direkt zurückschreiben.
2. **Im tatsächlichen Corecontainer** Pythonversion, SOABI, Architektur und
   installierte Distributionen prüfen. Der begrenzt geprüfte Stand ist
   Core 2026.11.0, CPython 3.14.10, `cpython-314-x86_64-linux-musl`, NumPy 2.3.2,
   SciPy 1.18.1 und Pandas 2.3.3. Fremde/abweichende Paketversionen oder vorhandene
   gleichnamige Dateien nicht überschreiben: erst Abhängigkeiten und Rückweg
   gesondert prüfen. Beim geprüften Wiederherstellungslauf fehlten alle fünf
   folgenden Distributionen im regulären Corepfad.
3. Ausschließlich den reparierten Wheel aus Abschnitt 4 und die vier reinen
   Runtime-Wheels in einen neuen privaten Transferordner unter
   `/config/adaptive_solar_dependencies/` kopieren. Ihre SHA256-Werte vor und
   nach dem Transfer vergleichen. Dort verbleibende Wheels sind nur ein
   Installationsvorrat, kein automatisch geladener Importpfad.
4. Auf dem administrativen Host, mit dem tatsächlichen Transferordner anstelle
   von `<transferordner>`, ausschließlich die geprüften Pakete installieren:

   ```bash
   docker exec homeassistant python3 -m uv pip install \
     --system --no-index --no-deps --only-binary=:all: \
     --find-links "/config/adaptive_solar_dependencies/<transferordner>" \
     scikit-learn==1.9.1 joblib==1.6.0 narwhals==2.27.1 \
     threadpoolctl==3.7.0 cloudpickle==3.1.2
   ```

   Dies verändert weder die Runtimepins noch das Lernmodell. Kein `--upgrade`,
   keine Buildvenv-Pakete und keine NumPy-/SciPy-/Pandas-Wheels übernehmen.
5. Native Imports, `homeassistant.util.package.is_installed('scikit-learn==1.9.1')`
   und synthetisches `GradientBoostingRegressor.fit/predict` wie in Abschnitt 5.4
   prüfen, **aber ohne** `sys.path.insert`: `sklearn.__file__` muss aus dem
   regulären Core-Paketpfad kommen. Numerische Paketdateien gegen die Baseline
   abgleichen, Konfigurationsprüfung ausführen. Eine globale `uv pip check`-Prüfung
   kann zusätzlich fremde Konflikte melden; diese nicht durch freie Upgrades
   reparieren und einen solchen Lauf nicht als vollständig erfolgreich ausweisen.
6. Nach wiederhergestellten Zugriffsrechten einmal Core neu starten und alle
   vorhandenen Einträge, aktuelle Prognosen, Registry-/Konfigurationsidentitäten
   sowie erhaltene Messintervalle und echte Tagesstartwerte prüfen. Keine
   Originalsensoren zwangsaktualisieren, um Frische zu erzeugen.

**Updategrenze:** Die Installation liegt im beschreibbaren Corecontainer, nicht
im HA-Image. Ein normaler Core-Neustart erhält sie; ein Core-Update, Rebuild oder
Containeraustausch kann sie entfernen. Die passenden, unveränderten Wheels können
dann nach erneuter ABI-/Abhängigkeitsprüfung wiederverwendet werden. HACS führt
diesen Vorgang nicht automatisch aus. Eine universelle updatefeste Binärlieferung
ist damit noch nicht gelöst; nicht pauschal alle künftigen Coreversionen freigeben.

**Gezielter Rückweg:** Nur wenn die Vorprüfung wie oben das vollständige Fehlen
dieser fünf Pakete belegt hat, ist das Entfernen genau dieser neu installierten
Distributionen per `python3 -m uv pip uninstall --system` im Corecontainer der
Paket-Rückweg, gefolgt von einem Neustart. Es stellt den früheren Fehlerzustand
wieder her, nicht eine funktionierende alte Coreversion. Vorhandene fremde Pakete,
`/config/deps` und Anlagendaten bleiben unberührt; kein Core-Downgrade und keine
Backupwiederherstellung sind Teil dieses Ablaufs.

## 6. Getrennte Nachweise

Build/Buildvenv-`pip check` belegen zunächst den Bauweg. Davon getrennt:

- **Musl-Testvenv:** Dependencycheck, HA-freie Kerntests, synthetische Learner-Parität zur Entwicklungsreferenz.
- **Nativer Core:** seine eigenen Imports und Fit/Predict. Metadaten, Setupform oder SSH-App-Fit ersetzen diesen Nachweis nicht.
- **Produktive Anlage:** qualifizierte Messintervalle und fairer [prospektiver Vergleich](../entwicklung/validierung.md).

Der Helfer lässt `native_core_verified`, `model_fit_verified`, `synthetic_parity_verified` daher auf `false`; spätere Nachweise brauchen eigene Interpreter-/Versions-/Quell-/Wheelhashbindung.

## 7. Grenzen des neuen Helfers

24 Tests mit synthetischen Wheels/gemockten Werkzeugen prüfen Hash/Plattform/Output, Befehlsfolge, Flags/Metadaten und Audit; kein Download/Compiler/HA.

Historischer echter Helferlauf: rootless `bwrap` im gebundenen Builder, neun Befehle Exit0/sieben Artefakte; der Docker-Aufruf selbst wurde damit nicht geprüft. Separat bestand das erzeugte Wheel Musl-`pip check`, 134 Kerntests und 144 synthetische Holdouts exakt gleich zur Entwicklungsreferenz. Konkrete Build-/Hostprotokolle werden privat geführt.

Helferflags bleiben false; native Imports und Fit/Predict benötigen eigene Hash-/Hostproben. [Historische Quelltests](../entwicklung/pruefnachweise.md) ersetzen keinen nativen Core-Fit oder realen Prognosevergleich.
