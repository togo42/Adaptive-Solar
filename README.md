# Adaptive Solar für Home Assistant

<p align="center">
  <img src="assets/adaptive-solar-logo.png" alt="Adaptive Solar: Sonne über einem Solarmodul mit aufsteigender Prognosekurve" width="240">
</p>

[Dokumentation](docs/README.md) · [Versionshinweise](docs/releases/README.md) · [Fehler melden](https://github.com/togo42/Adaptive-Solar/issues)

Adaptive Solar verbindet Open-Meteo-Wetterprognosen, PV-Physik und lokale
Residualmodelle. Die Integration prognostiziert das **verfügbare PV-Potenzial
ohne betriebliche Abregelung**: Leistung, Resttag und bis zu sechs Folgetage,
abhängig von der eingestellten und tatsächlich verfügbaren Wetterabdeckung.

Unterschiedliche Stringausrichtungen, gemeinsame AC-/DC-Ausgangsstufen und
wiederkehrende Verschattung werden berücksichtigt. Frische HA-Messungen für
Temperatur, Wind, horizontale Globalstrahlung und PV-Leistung unterstützen
kurzfristige Korrekturen. Ohne qualifizierte Lernhistorie bleibt die Physik aktiv.
Ein gemeinsamer Zähler kann keine Einzelstringverluste identifizieren.

**Installierter Stand 0.2.24, Stand 06.11.2026: Installation bestätigt,
aktueller Vierquellen-/Exportnachlauf erfolgreich; keine vollständige Gesamtabnahme.** Nach manuellem
Download und genau einem Core-Neustart durch den Nutzer sind Core 2026.11.0,
die exakten Releasekomponenten und vier geladene Einträge bestätigt. Im lesenden
Nachlauf vom 6. November bestehen alle vier nativen Eingangsgates und die vier
neuesten Originalexportprüfungen unter unveränderten Frische-/Qualitätsregeln.
Die zwei Frischefehler vom 5. November bleiben historische negative Originale;
spätere Zustände heilen sie nicht. Messintervalle und verbleibende historische
Tageswerte/-kurven samt Provenienz sind exakt erhalten; reguläre Retention und
Schattenfortschreibung sind getrennt geprüft. Der erneute Gesamtaudit mit der
eingefrorenen Baseline vom 5. November ist negativ; eine neue fremde HA-Repair ist gesondert offen.
Keine Gates, Quellenbindungen oder Lernstände wurden dafür verändert.
Tests und Reviews belegen keinen Genauigkeitsvorsprung gegenüber anderen
Integrationen; dafür bleibt ein [prospektiver Vergleich](docs/entwicklung/validierung.md) erforderlich.

**[0.2.24](docs/releases/release-0.2.24.md) ist veröffentlicht und installiert.**
Der [Release](https://github.com/togo42/Adaptive-Solar/releases/tag/v0.2.24)
bindet unveränderlich Commit `f21ad29c8341f9d784e686b4a74ab9a6a4097c93`;
alle vier veröffentlichten Assets wurden heruntergeladen und bytegleich geprüft.
Die additive [Schattenfenster-Diagnose](docs/technik/schattenfenster-diagnose.md)
macht ausschließlich aktuell gespeicherte Sonnenfenster je Stufe lesbar
(höchstens 648), ohne Änderung der Modell-/Freigabe-/Fitregeln oder Speicher-/Archivformate.
Der HA-native ML-Liefervertrag aus 0.2.23 einschließlich unveränderlicher
Dependency-Release-URL bleibt erhalten; es gibt kein neues Dependency-Artefakt.
Dashboardressourcen und Karten des getrennten HA-Config-Projekts gehören nicht
zu diesem Integrationsauftrag; hier wurden sie nicht geändert. Die separate
Liste angenommener ML-Ziele ist nicht Bestandteil dieses Releases.
Vor einem produktiven Quellwechsel sind Quellenbindungen frisch zu prüfen:
bei 0.2.23 geschlossene Perioden bleiben geschlossen; nur noch offene Perioden
müssen vor Dateiwechsel/Neustart am exakten realen UTC-Schnitt geschlossen werden.
Neue Producerpins benötigen eine separate Freigabe. Originalarchive, alte
Quellumgebung, Pins und Checkpoints bleiben erhalten. Der Nutzer hat den manuellen
Download und den einmaligen Neustart bereits ausgeführt; der Agent wiederholt
diese Aktionen nicht und umgeht keine Marketplace-Kontobestätigung.

## Installation und Bedienung

1. [Plattform und Abhängigkeiten prüfen](docs/anwendung/installation.md).
   Die Metadatenuntergrenze ist Core **2026.10.2**; der native Testvertrag
   verwendet **2026.10.4 / Python 3.14**. Frühere Nachweise für .2/.3 sind
   historisch. Die automatische Musl-Lieferung gilt nur für **HAOS amd64 /
   normales CPython 3.14 / Musl ≥1.2**; andere ABIs benötigen neue Artefakte.
2. In **Marketplace** unter **Benutzerdefinierte Repositories**
   `https://github.com/togo42/Adaptive-Solar` als **Integration** hinzufügen,
   eine veröffentlichte Version herunterladen und Home Assistant neu starten.
3. Unter **Einstellungen → Geräte & Dienste → Integration hinzufügen → Adaptive Solar**
   Standort, Ausgangsstufen und Strings einrichten. Bestehende Einträge beim Upgrade
   weiterverwenden. [Bedienung und Fehlerbehebung](docs/anwendung/bedienung.md).

Marketplace ist seit Core 2026.11 integriert und ersetzt dort HACS. Auf älteren
Coreversionen bleibt der frühere HACS-Weg anwendbar; die kompatible Metadatendatei
heißt weiterhin `hacs.json`.

**Ab 0.2.23:** Beim ersten Start in einem frischen kompatiblen Corecontainer
installiert HA die fehlende ML-Bibliothek automatisch. Kein Dockerzugriff, kein
Compiler und kein Wiederaktivieren von `/config/deps` sind dafür nötig. Der erste
Start benötigt GitHub-/PyPI-Zugang; eine gesunde vorhandene ML-Installation
verursacht durch diesen Bootstrap keinen Netzwerkzugriff. Dies ist keine Garantie
für beliebige zukünftige Python-/Core-/NumPy-/SciPy-Versionen.
[Installation, Sicherung und Rückweg](docs/anwendung/installation.md).

Je String werden kWp, Neigung, Azimut und Verluste angegeben:
**0° Nord / 90° Ost / 180° Süd / 270° West**. AC-Stufen haben Wirkungsgrad und
AC-Grenze; DC-Stufen eine nominelle Ausgangsgrenze und optionale Zusatzverluste.
Fiktive [AC-](examples/site.json) und [DC-Beispiele](examples/site-dc.json)
zeigen die herstellerunabhängige Konfiguration. Optionale Horizontprofile und
Morgen-/Abenddämpfung sind Konfigurationsannahmen, keine vermessene Teilverschattung.

Lernen benötigt kumulative PV-Energie am richtigen Messpunkt, der Leistungsnowcast
Leistung in W. Messlücken bleiben fehlend; aktive oder unbekannte konfigurierte
Abregelung sperrt betroffene Lern-/Leistungsbeobachtungen. Die
[Messkontinuitätsregeln](docs/technik/measurement-learning.md) und die
[Ablehnungsdiagnose](docs/technik/ablehnungsdiagnose.md) erklären verwendbare Labels.
Ausgabequalität ist keine Genauigkeitsklasse. Datenflüsse und lokale Aufbewahrung
stehen unter [Datenschutz](docs/anwendung/datenschutz.md).

## Entwicklung

Für native HA-Tests Python 3.14 verwenden; der HA-unabhängige Modellkern unterstützt
Python ab 3.13. Der [Entwicklungsleitfaden](docs/entwicklung/entwicklung.md) beschreibt
die reproduzierbare Installation mit automatischer Übernahme der Manifest- und ML-Pins.

```bash
python3.14 -m venv .venv
.venv/bin/python -m pip install '.[test,ha-test]' 'pvlib==0.16.1' 'scikit-learn==1.9.1'
.venv/bin/python -m pip check
.venv/bin/python -m pytest -q --cov=custom_components.adaptive_solar --cov-branch \
    --cov-report=term-missing:skip-covered --cov-report=xml:artifacts/coverage.xml
.venv/bin/ruff check custom_components tests scripts tools/ml_runtime
```

Synthetische Offline-Demo:

```bash
.venv/bin/python scripts/forecast.py --config examples/site.json --synthetic \
    --as-of 2026-06-21T08:00:00+02:00 --output artifacts/demo.json
```

Die synthetische Demo erzeugt ausschließlich das erste konfigurierte
Wettermodell; weitere Modelle werden ausdrücklich als nicht verfügbar berichtet.
Clear-Sky-Werte sind Mittelpunktnäherungen der jeweiligen Zelle. Die letzte,
gegebenenfalls verkürzte Zelle reicht auch bei halben/viertel Zeitzonenoffsets
bis zum lokalen Ende des Prognosehorizonts. Das ist ein Softwarebeispiel,
kein archivierter Wetter- oder Gütenachweis.

`--live` ruft Open-Meteo auf und ist nicht rückdatierbar. Die Forecast- und
Auswertungs-CLI schützen Eingaben sowie Quell- und Ressourcendateien gegen
Ausgabe-Aliase. Berichte bleiben außerhalb von `scripts/` und
`custom_components/` und werden nach erneuter Pfadprüfung atomar veröffentlicht.
Die Integration enthält außerdem einen separaten
[Offline-Kandidaten zur Prüfung der Trainingsabdeckung](docs/technik/learning-support-guard.md)
des Residual-Lerners. Er verändert keine produktiven HA-Prognosen.
Ein weiterer [Offline-Adapter qualifiziert Recorder-Iststunden](docs/archiv/istwert-qualitaetsadapter.md)
aus Originalintervallen und belegten Quellenbindungen; ungeprüfte Quellen bleiben Diagnose.
Der Qualitätsadapter unterstützt auch optionale fortlaufende Aufnahme mit
Quellenpins je Originaldelta und einen lokalen Probelauf ohne HA-Zugriff.
Für die fortlaufende Qualitätsprüfung werden vollständige Forecastoriginale
einzeln geprüft und danach als kompakte Konfigurationsbelege aufbewahrt;
die unveränderten Originale und alle Konfigurationswidersprüche bleiben gebunden.
Die nachfolgende lokale Überarbeitung schützt auch Hoststatusziele, bündelt die
Ausgabeauswahl der Auswerter und trennt die gemeinsame Qualitäts-Einlesehilfe
von den CLIs. Der [Ablauf für Fehlerfamilien](docs/entwicklung/review-fehlerfamilien.md)
beschreibt die gemeinsame Nachprüfung; ältere Vollreviews gelten ausschließlich
für ihre damaligen Quellstände.
[Datenverträge](docs/technik/implementation-contract.md),
[Vergleichsaufnahme](docs/entwicklung/benchmark-aufnahme.md) und
[Reviewablauf](docs/entwicklung/validierung.md#4-lokale-prüfung-und-review)
ergänzen die Entwicklung. Private Zuordnungen und Betriebsprotokolle gehören unter
ignoriertes `data/`, generierte Artefakte unter `artifacts/`, rohe Reviewdaten unter
`reviews/private/`.

## Optionaler Archivbetrieb

Der [Originaldatenexport und Replay](docs/archiv/archivbetrieb.md) archiviert
ursprüngliche Wetter-, Beobachtungs- und Prognosedaten auf einem separaten Host.
Export und Collector werden bewusst eingerichtet; die Prognose benötigt keinen
Archivhost. Die [Hostinstallation](docs/archiv/archiv-host-installation.md)
verwendet eine [eigene Laufzeit ohne HA Core](docs/archiv/archiv-runtime-ohne-ha.md).
Marketplace aktualisiert weder externe Hostdienste noch Dashboardressourcen.
Die [Laufzeittelemetrie](docs/entwicklung/archiv-laufzeittelemetrie.md) trennt
Lockwartezeit, Kindaufrufe, Statistik und Timeout-/Betriebssystemfehler.
Für den Archivhost gibt es ein ausdrücklich zu aktivierendes
[natives Qualitätsbackend](docs/archiv/native-qualitaetsbackend.md) mit
Manifest-/ML-Pins und Python-Rückfall. Die HA-Integration benötigt kein Rust.

Originaldateien und ein wiederaufbaubarer SQLite-Index sind die Speicherbasis.
24 Monate Retention sind eine Einstellung; der tatsächliche Platzbedarf muss
nach Pilotdaten und erneut nach drei und sechs Monaten bewertet werden.
Reproduzierbarer Replay und Ensemblequantile ersetzen keine lokal gemessene Güte.

Release 0.2.21 bietet [Speichersparprofile](docs/archiv/speichersparprofile.md):
getrennte Aufnahmeintervalle für Istwerte und Referenzprognosen, kompakte
Qualitätsberichte und eine optionale reduzierte Nachtdiagnostik. Bestehende
Einstellungen bleiben ohne ausdrückliche Auswahl erhalten. Das Nachtprofil ist
in einer Installation mit Erhaltungsprüfung aktiviert; ein vollständiges
Tag-/Nachtfenster zur Verbrauchsmessung steht noch aus.

## Recherche und Quellen

Die [Rechercheübersicht](docs/README.md#recherche-und-planung) erschließt Grundlagen,
Werkzeuge, Wettermodelle und historische Arbeitspakete unter `docs/recherche/`.
Literaturergebnisse sind keine erwarteten lokalen Resultate. Referenzintegrationen:
[Helios Forecast](https://github.com/ReikanYsora/Helios-Forecast) und
[Open-Meteo Solar Forecast](https://github.com/rany2/open-meteo-solar-forecast);
es wird kein Quellcode daraus übernommen.

Primärquellen und konkrete Parameter stehen im
[Implementierungsvertrag](docs/technik/implementation-contract.md).
Bibliothekslizenzen und die API-Bedingungen der Wetterdienste gelten getrennt;
weitere Hinweise unter [Datenschutz](docs/anwendung/datenschutz.md).

## Lizenz

Copyright (C) 2026 Torsten Godau.

Die eigenen Inhalte dieses Repositories, einschließlich Quellcode, Tests, Beispielen,
Dokumentation und Projektgrafiken, stehen, soweit urheberrechtlich geschützt, unter
der **GNU General Public License, ausschließlich Version 3** (`GPL-3.0-only`).
Der vollständige unveränderte Lizenztext steht in [LICENSE](LICENSE); eine identische
Kopie wird für Marketplace innerhalb der Integration mitgeliefert.

Private und kommerzielle Nutzung sind erlaubt. Wer vom Copyleft erfasste geänderte
Versionen weitergibt, muss sie ebenfalls unter GPL Version 3 bereitstellen und den
Empfängern den zugehörigen Quellcode gemäß den Lizenzbedingungen zugänglich machen.
Rein private Änderungen müssen nicht veröffentlicht werden. Die Software wird ohne
Gewährleistung im Umfang der Lizenz bereitgestellt.

Externe Bibliotheken und zitierte fremde Inhalte behalten ihre jeweiligen Lizenzen;
die Bedingungen und Attributionspflichten der Wetterdienste gelten zusätzlich.
Die Projektlizenz erlaubt keine kommerzielle Nutzung von Open-Meteos freier API
entgegen deren Nutzungsbedingungen. Hinweise zur Verwendung des Projektlogos:
[Logo und Gestaltung](docs/branding.md).
