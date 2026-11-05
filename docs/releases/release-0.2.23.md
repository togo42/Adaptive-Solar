# Adaptive Solar 0.2.23

Stand: 05.11.2026, **veröffentlicht und über Marketplace installiert** als
[v0.2.23](https://github.com/togo42/Adaptive-Solar/releases/tag/v0.2.23),
Releasecommit `593c8a0e0c9f7863aa43c98a31221e337a545671`.
Dieser Stand ersetzt die manuelle Paket-Reparatur nach dem Core-2026.11-Update
durch einen begrenzten HA-nativen Startpfad. Veröffentlichung, Installation und
die vollständige begrenzte Erhaltungsabnahme sind abgeschlossen. Ein lokaler Test
allein ist dafür kein Ersatz.

## Änderung und unveränderte Fachlichkeit

Core 2026.11 lädt den alten `/config/deps`-Pfad nicht mehr. Die Integration prüft
deshalb vor jedem Coordinator-/Storeaufbau die exakt installierte
scikit-learn-Version 1.9.1 und den tatsächlich benötigten nativen Learnerimport.
Eine gesunde vorhandene Version benötigt keinen Installeraufruf. Erst bei
fehlender Bibliothek wird HAs eigener `async_process_requirements` mit dessen
Lock, Executor und Constraints verwendet. Kein eigener pip-/uv-Unterprozess,
kein globaler Importpfad und kein Compiler gehören zum Integrationsstart.

Auf qualifiziertem CPython 3.14/Linux x86_64 mit Musl wird ein hashgebundener
Liefercontainer aus einem separaten unveränderlichen Dependency-Release verwendet;
auf qualifiziertem glibc bleibt das normale PyPI-Requirement erhalten. Das Bundle
liefert denselben bereits geprüften scikit-learn-Musl-Wheel unverändert. Seine
GNU-Runtimebibliotheken benötigen eigene Lizenz- und Quellbeigaben; diese gehören
zum [Liefervertrag](../technik/ml-runtime-bundle.md), nicht zur Projektlizenz allein.

Physik, scikit-learn-Version, Lern- und Freigabegates, Messkontinuität,
Konfigurationsfingerprints und Storeformate werden nicht geändert. Der
HA-freie Archivhost bleibt HA-frei; seine Installation und CI lesen den expliziten
ML-Pin zusätzlich aus `runtime_requirements.json`, statt auf die breitere normale
Projektabhängigkeit zurückzufallen.

## Betriebsgrenzen

- Der erste Start in einem frischen kompatiblen Corecontainer benötigt Zugriff
  auf das veröffentlichte GitHub-Dependency-Artefakt und auf PyPI.
- Ein vorhandenes gesundes scikit-learn 1.9.1 verursacht durch den Bootstrap
  keinen Netzwerkzugriff. Andere Integrationen und HAs übrige Requirements
  können unabhängig davon Netzwerkzugriff benötigen.
- Andere vorhandene Versionen, kaputte native Imports, ausgeschaltete automatische
  Paketinstallation oder unbekannte Liefer-ABIs führen zu einem klaren Abbruch vor
  Coordinator-/Storeaufbau. Keine laufende fremde Bibliothek wird ersetzt.
- Beim notwendigen Installationszweig gilt HAs Installerverhalten einschließlich
  `--upgrade` und Coreconstraints. Das Bundle pinnt seinen eigenen Payload, nicht
  pauschal sämtliche künftigen transitive Bibliotheken. Ein tatsächlicher
  Vorher-/Nachhervergleich im Zielimage ist deshalb ein eigenes Abnahmekriterium.
  HAs Manager installiert Requirements einzeln; zusätzliche Manifestpins für
  Begleitpakete wären deshalb keine gemeinsamen Resolverconstraints. Joblib,
  Narwhals und Threadpoolctl sowie deren Abhängigkeiten werden anhand der
  originalen Paketmetadaten aufgelöst.
  Die Integration verspricht für transitive Pakete keine unveränderten
  Versionsnummern bei einer notwendigen Neuinstallation.
- Unterbrochene native Installationen können im Executor noch auslaufen. Es gibt
  weder eigene Hintergrundreparaturen noch eine automatische Retry-Garantie.
- Updatefest bezeichnet die automatische erneute Lieferung nach einem
  Containerwechsel innerhalb des qualifizierten Interpreter-/Plattformvertrags,
  keine Zusage für beliebige zukünftige Python-, Core- oder Bibliotheksversionen.

## Marketplace und Upgrade

Ab Core 2026.11 wird **Marketplace** statt HACS verwendet. Die kompatible
Repositorymetadatendatei heißt weiterhin `hacs.json`. Das Vorab-Release
`v0.2.23-runtime.1` ist ein Dependency-Artefaktrelease; für die Integration ist
das reguläre **v0.2.23** bestimmt.

Vor Installation Komponentenstand, aktuelle Konfiguration und Erhaltungsbaseline
sichern. Die Marketplace-Erstnutzungswarnung vorab selbst mit dem installierenden
Konto bestätigen, bei Archivbetrieb bereits vor Timerpause/Quellenschließung.
`can_install=true` allein belegt diese kontogebundene Voraussetzung nicht.
Ein Agent darf sie nicht stellvertretend akzeptieren oder umgehen.
In Marketplace aktualisieren, einmal Core neu starten und vorhandene
Einträge, Entity-/Geräteidentitäten, Tagesstartwerte und Messhistorie prüfen.
Keine Integration löschen und keine `.storage`-Dateien zurückschreiben.

Die neuen Pythonbytes ändern den vollständigen Producerhash. Externe qualifizierte
Quellenperioden müssen vor dem tatsächlichen Dateiwechsel halb offen geschlossen
werden. Alte Pins, Originale, Konfigurationsanker und Attestationen bleiben erhalten.
Neue Producerbindungen benötigen eigene Freigabe; ein Dependencyfix qualifiziert
keine neue Quelle. Archivhostdienste werden nicht durch Marketplace aktualisiert.

## Prüfung und Nachweisgrenzen

Lokal bestanden unter Python 3.14.4 mit echtem Core 2026.10.4 und Plugin 0.13.375
**3.206 Tests bei 91,51 % kombinierter Zeilen-/Zweigabdeckung**; das 90-%-Gate
bleibt unverändert. Zwei ausdrücklich opt-in geschaltete Real-Rustkerneltests
wurden nicht angefordert und übersprungen; keine HA-Tests wurden übersprungen.
31 SQLite-ResourceWarnings wurden gemeldet und bleiben von diesem Lieferfix
getrennt. Nach dem Manifestabgleich bestanden die 66 gezielten Bootstrap-,
Cold-Import- und Archivinstallerfälle erneut. Das Bundle hat 80 synthetische
Sicherheits-/Plattform-/Paketierungstests; der private Cutovercontroller 79.

Im exportierten offiziellen Core-2026.11.0-Image
`sha256:7ae9d514ead3674f96968999293417706cc8a53940c6bf04551908e35bdb466b`
mit Python 3.14.10/Musl installierte HAs eigener Requirementsmanager den finalen
Lieferbundle erfolgreich in eine separate leere ML-Paketschicht. Der native
Learnerimport und synthetisches Fit/Predict bestanden. NumPy 2.3.2, SciPy 1.18.1
und Pandas 2.3.3 behielten Versionen und alle geprüften Python-/SO-/Metadatenbytes.
Ein zweiter frischer Prozess in abgeschaltetem Netzwerknamespace bestand mit
verbotenem Installeraufruf. Danach bestand derselbe Installationspfad in einer
zweiten sauberen Schicht über die unveränderte **öffentliche** Runtime-URL.
Alle aktiven Requirements von sklearn, Begleitern und pvlib waren erfüllt.
Auch sämtliche 908/1.437/1.517 erfassten NumPy-/SciPy-/Pandas-Dateien außer
Bytecode blieben gegenüber dem Originalimage bytegleich. Ein absichtlich falscher
öffentlicher SHA256 wurde von HAs tatsächlichem uv-Installer vor Installation
abgelehnt. Das ist keine vollständige 2026.11-Testsuite und ersetzt keinen
produktiven Marketplace-/Erhaltungsreadback.

Das Dependency-Vorabrelease
[`v0.2.23-runtime.1`](https://github.com/togo42/Adaptive-Solar/releases/tag/v0.2.23-runtime.1)
ist auf Commit `0dc2f4555d8ea64bcae551d94ca15f5dfca4c9f8` veröffentlicht.
Sechs Assets einschließlich sämtlicher Quellbeigaben wurden öffentlich
heruntergeladen und bytegleich geprüft. Der Lieferbundle-SHA256 ist
`85370dd890ed4d068f4e16afa69c65b3c327b44570ddd624ffa964cbf58f7fea`.
Die [CI dieses Bundlecommits](https://github.com/togo42/Adaptive-Solar/actions/runs/42083386169)
ist erfolgreich. Auch die CI des finalen Integrationsstands ist für
[main](https://github.com/togo42/Adaptive-Solar/actions/runs/42085283107),
[Arbeitsbranch](https://github.com/togo42/Adaptive-Solar/actions/runs/42085283042)
und [Versionstag](https://github.com/togo42/Adaptive-Solar/actions/runs/42085347914)
erfolgreich; der Taglauf bestand **3.208 Tests ohne Skips bei 91,51 % Abdeckung**,
einschließlich der beiden optionalen Real-Rustfälle. Die expliziten nativen
Differentialgates und der HA-freie Archivhostjob sind ebenfalls grün.
Wheel, sdist und Integrations-ZIP enthalten exakt
die 44 vorgesehenen Komponentenfiles; alle 36 Pythonmodule wurden aus einem
frisch regulär installierten Wheel importiert.

Alle vier regulären Releaseassets wurden öffentlich heruntergeladen und
bytegleich geprüft:

| Asset | SHA256 |
| --- | --- |
| `adaptive_solar.zip` | `c89075e7ab66673a1c41c5da44e29d43e266cc5f912a87f2956171be1090a911` |
| `adaptive_solar_ha-0.2.23-py3-none-any.whl` | `10e61cc7ba21a544165efaab097e3450ed3d33e0ba6f274b93912cceaa9dd6cf` |
| `adaptive_solar_ha-0.2.23.tar.gz` | `162e51859abae2716240755c11e893967a4c31a0c21e4cf80fa03dd1a315be3f` |
| `SHA256SUMS` | `e4883ec869ce1b1d5258ab62bc3a7ff7a6c3227d88eb533a6596d41b4f70bfd5` |

## Produktive Installation und Erhaltung

Der erste native Marketplace-Installationsaufruf wurde vor jedem Dateiwechsel
wegen der nicht bestätigten Erstnutzungswarnung des verbundenen Kontos abgelehnt.
Der Betreiber führte daraufhin Download und Neustart selbst in Marketplace/HA
aus. Der Agent wiederholte weder Download noch Neustart und umging keine Warnung.
Die Bestätigung ist kontogebunden; beim API-Konto kann sie weiterhin fehlen.
Für spätere automatisierte Marketplace-Downloads diese Voraussetzung separat
klären, statt `can_install=true` als ausreichenden Nachweis zu verwenden.
Der automatische ML-Startpfad benötigt diese Marketplace-Kontobestätigung nicht.

Frischer nativer Readback unter unverändertem **Core 2026.11.0** bestätigt
Version 0.2.23, exakt 44 Release-Komponentenfiles und den vollständigen Hash aller
36 Pythonfiles. Vier vorhandene Einträge sind geladen. Konfiguration, Optionen,
Entity-/Unique-IDs, vier Geräte sowie Energy-/Dashboardbezüge blieben erhalten.
Alle 1.804 an einem vorab eingefrorenen UTC-Cutoff abgeschlossenen Messintervalle
blieben als Multiset erhalten. Ebenso unverändert sind vergangene/heutige
Tagesstartwerte, Stundenkurven und Originalprovenienz, acht native Tag0-Anzeigen
einschließlich Alt-Totalaliases sowie die abgeglichenen Comparisonoriginale.
Begrenzte Forecastrepräsentanten werden getrennt davon behandelt; die Abnahme
behauptet keine Bytegleichheit ständig fortgeschriebener kompletter Stores.

Der erste Readback unmittelbar nach dem Neustart blieb negativ: Die ersten
Forecasts wurden noch während des HA-Starts erzeugt und einzelne Eingangssensoren
hatten noch keine neuen echten Berichte. Dieses negative Original blieb erhalten.
Nach dem regulären Folgezyklus bestanden **alle 97 eingefrorenen globalen
Erhaltungsprüfungen und vier vollständige Originalexportprüfungen**. Je Eintrag
sind native ML-Version 1.9.1, neuer Producer, ursprüngliche Site-/State-/
Wetterabhängigkeiten, gültige Eingänge und drei vollständige lokale Folgetage
belegt. Das native Logbuch bestätigt genau einen Core-Start nach dem Wechsel.
Keine Sensorfrische, Forecastrefreshes oder zusätzlichen Neustarts wurden erzwungen.

Konfiguration gültig, keine offenen Repairs und in den vier getrennten begrenzten
Logabfragen keine Adaptive-Solar-/blockierenden Setup-/Entryfehler. Der produktive
ML-Importnachweis verbindet den verpflichtenden gepinnten Setup-Kontrollfluss
mit diesen danach geladenen Einträgen und frischen Originalmetadaten. Er ist kein
separater produktiver Fit/Predict- oder Missing-Package-Installationsversuch;
die frische Installation stammt aus der isolierten offiziellen Imageprüfung oben.

Vor dem Dateiwechsel wurden genau vier alte aktive externe Quellenperioden am
tatsächlichen UTC-Cutover halb offen geschlossen; Originalpins und alle übrigen
Policybytes blieben erhalten. Keine neuen qualifizierten Bindungen wurden erzeugt.
Neue externe Vergleichsstunden bleiben bis zur gesonderten Quellenfreigabe
unqualifiziert. Archivhostcode, Runtime und Timer-Enabledzustände wurden nicht
aktualisiert. Der pausierte Actuals-Timer wurde nach dieser bestandenen Abnahme
auf seinen ursprünglichen Zustand zurückgestellt; Observations bleibt deaktiviert.
Alle sechs Timerzustände und der weiterhin geschlossene Policyhash wurden
unverändert rückgelesen.

Das ausdrücklich ausgewählte vorhandene geschützte HA-Konfigurations-/SSL-Backup
wurde weiterverwendet; kein neues Backup, keine Recorder-/App-Sicherung und kein
Restore wurden ausgeführt. Acht aktuelle Storeoriginale und die bytegeprüfte alte
Komponente sind gesonderte Erhaltungs-/Rückwegbelege, keine Erlaubnis zu direkten
`.storage`-Writes. Entschlüsselung/Vollrestore sind nicht getestet.

Die nachträgliche Statusdokumentation erweitert den eingefrorenen Quellreview
nicht. Release-Tag, Assets und Komponentenbytes bleiben unverändert.

Lokale Subagentenprüfungen sind fokussierte unabhängige Nachprüfungen, kein neuer
externer Gesamtquellreview. Paketbau, synthetischer Fit und Laufzeiterhaltung
belegen weder physische Quellenqualität noch produktives Lernen oder einen
Genauigkeitsvorsprung gegenüber Referenzintegrationen.
