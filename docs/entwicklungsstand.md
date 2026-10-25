# Entwicklungsstand und offene Nachweise

Stand: 25.10.2026. **Nach dem Betreiberupdate auf Core 2026.10.4 geprüft: Adaptive Solar 0.2.7, vier geladene Anlageneinträge mit aktuellen Prognosekurven.** Lokale Kompatibilität des Entwicklungsstands 0.2.8 ist ebenfalls geprüft. Produktiver ML-Fit und bessere Prognosegüte bleiben offen.

## 1. Implementierung und Prüfung

[Verträge](implementation-contract.md), [Review](review-findings.md). Implementierung durch drei Subagenten mit hohem Aufwand.

Je **752 Tests bestanden**, null übersprungen: HA2026.10.2/Plugin0.13.373 und HA2026.10.3/Plugin0.13.374, Python3.14.4, normale Wheel-Installation. JUnit: `artifacts/tests-0.2.7-ha-2026.10.2.xml`/`.3.xml`. Sieben Kernmodule unverändert zu0.2.6; dessen231 Musl-Kerntests sind über `artifacts/core-compatibility-0.2.7.json` gebunden, kein neuer Musl-Lauf. Je73 gezielte AC-/DC-/Filtertests ergänzen dies. Ruff/Dependency-/Paket-/Importprüfungen bestanden; GitHub-Workflow hier nicht ausgeführt. Historische Details liegen im lokalen Archiv `artifacts/releases/0.2.7-reviewed/source/docs/entwicklungsstand.md`.

**Lokaler Korrekturstand 0.2.8:** normale Wheel-Installation, Python 3.14.4/glibc; jeweils 814 Tests bestanden, null übersprungen:

| HA Core | Testplugin | Laufzeit |
|---|---|---:|
| 2026.10.2 | 0.13.373 | 83,84 s |
| 2026.10.3 | 0.13.374 | 83,60 s |
| 2026.10.4 | 0.13.375 | 80,58 s |

JUnit: `artifacts/tests-0.2.8-final-ha-2026.10.2.xml`/`.3.xml` und `artifacts/compatibility-ha-2026.10.4-0.2.8/tests.xml`. Der zusätzliche .4-Lauf nutzt eine frische Umgebung mit offiziellen Core-Constraints; Paketimport außerhalb des Repositories, alle 21 installierten Paketdateien, Ruff und `pip check` sind geprüft. Ein lokaler `/tmp`-Platzmangel beim ersten Installationsversuch wurde durch die neue Umgebung auf dem Projekt-Datenträger umgangen; bestehende Umgebungen/Belege blieben erhalten.

Enger As-of-Join-Fix mit zusätzlichen Grenz-/Duplikat-/Diagnostikfällen; Messgates und Fit-Filter unverändert. Hinzu kommen strengere Reviewtransportprüfungen einschließlich 137 gezielter Fälle. Sieben Modellkernmodule sind unverändert. Die beiden 0.2.8-Wheels unterscheiden sich ausschließlich in ZIP-Zeitstempeln; alle Nutzdaten sowie die 21 Komponenten im Installations-ZIP sind bytegleich (`artifacts/package-validation-0.2.8-final.json`). Kein neuer Musl-Lauf. Produktiv bleibt Integrationsversion 0.2.7.

## 2. Live-Stand und Grenzen

Freigegebenes Update: frisches verschlüsseltes Konfigurations-/App-Backup ohne Recorder-Datenbank,21 neue/21 aufbewahrte alte Integrationsdateien und1.342 unveränderte Abhängigkeitsdateien per Hash zurückgelesen, genau ein zusätzlicher Core-Neustart.

Vor dem angekündigten Core-Update: HA2026.10.2/Python3.14.6, drei Entries geladen,60 Sensoren/sechs Geräte. Wetter, Prognosekurven, Resttag/Folgetage, GHI-Anwendung, Persistenz und gespeicherte Optionen geprüft. Optionskorrektur nur mit Entry-Reload. Konfiguration gültig, null aktive Repairs. Verwaltungsoberfläche visuell nicht belegt. Ersttags-Tagesbeginnsnapshot fehlt korrekt. Das freigegebene generische Abregelungssignal ist ausschließlich dem DC-Eintrag zugeordnet.

Nach dem Betreiberupdate: Core 2026.10.4/Python 3.14.9, System gesund, Konfiguration gültig, null aktive Repairs. Die drei zuvor installierten Einträge und ein inzwischen vorhandener zusätzlicher Eintrag sind geladen. Je 154 Prognosepunkte, vollständige Resttagsabdeckung und keine Wetterproviderfehler; Temperatur, Wind und GHI sind gültig. Die GHI-Korrektur wird zum aktuellen Ausgabezeitpunkt wegen einer zu schwachen Referenzstrahlung korrekt ausgelassen. Alle 21 produktiven Integrationsdateien entsprechen weiterhin 0.2.7. Dies belegt aktuellen Forecast-Betrieb, keinen nativen qualifizierten ML-Fit.

Lernbindungen leer: Import der Lernbibliotheken im Forecast-Lifecycle belegt keinen produktiven Fit. Messquellenqualifikation und nötige Abregelungsevidenz bleiben offen; Betreiberangabe ungedrosselten AC-Betriebs verlangt keine Herstellerdiagnostik. Hardwareunabhängige Schnittstellen sind keine Genauigkeitszusage.

Keine Energy-Umschaltung und kein dauerhafter Vergleichsjob. Die gesondert freigegebenen West-Referenzen wurden auf dieselbe Ausgangsgrenze angeglichen. Ein erster prospektiver Einmal-Capture enthält ausschließlich künftig vollständige gemeinsame Stunden; er gehört nicht zur vorab festgelegten Hauptkohorte. Ein lokaler90-Tage-Walk-forward mit60 Tagen Anlauf und30 Auswertungstagen ist abgeschlossen. Er verwendet nachträglich beschaffte ursprüngliche Wetterläufe und angenommene Verfügbarkeitszeiten; Messqualifikation und vollständige lernende Helios-Referenz fehlen. Er ist bedingte historische Diagnose, kein produktiver oder prospektiver Genauigkeitsnachweis. Private Parameter/Ergebnisse bleiben außerhalb Git/Review. [HAOS-Bauweg](haos-installation.md), [Messplan](validierung.md): mindestens30 vollständige gepaarte Tage je Stratum. Kein belegter Vorsprung gegen beide Referenzen.

## 3. GitHub-Erstveröffentlichung

Quellstand **0.2.8**, Dokumentation, Tests, Recherche und Logo werden unter [togo42/Adaptive-Solar](https://github.com/togo42/Adaptive-Solar) bereitgestellt. Die Veröffentlichung ändert keine produktive HA-Installation. Der anschließend gültig abgeschlossene Implementierungsreview bindet Commit `0285445`, 76 vollständige Originale und sechs unveränderte Forschungsreferenzen; Umfang und Grenzen stehen im [Reviewnachweis](review-findings.md).

Frische lokale Vorprüfung: **758 Tests bestanden**, null übersprungen, 66,75s; Ruff und `pip check` erfolgreich. Der JUnit-Bericht liegt lokal unter `artifacts/github-preflight-tests.xml`. GitHub Actions führt die vorhandene Testsuite nach dem Push separat aus.

Die genannten `artifacts/`- und `reviews/private/`-Pfade bezeichnen lokale, ausgeschlossene Nachweise. Diese Dateien und private Installationsparameter sind im öffentlichen Repository nicht enthalten.
