# Entwicklungsstand und offene Nachweise

## Vorbereitung von 0.2.11

Stand: 26.10.2026. 0.2.11 ist zur vollständigen neuen Prüfung und Veröffentlichung
vorbereitet; produktiv ist zu diesem Zeitpunkt weiterhin 0.2.10 geladen. Der
Gesamtblick umfasst Lizenzmitlieferung, alle öffentlichen Anleitungen, Plattform-/
Versionsgrenzen, native Energy-/Messsemantik, Recherchequellen und Reviewtransport.
Zusätzlich zum Auditnachtrag wurden der neue Versionsstand und die Einbeziehung
endungsloser Lizenzdateien samt Regression ergänzt. Das neue feste lokale
Transportbudget und seine unveränderten Fail-Closed-Grenzen stehen im [Verfahren](validierung.md).

Frische Quelltests: je **894 ohne Fehler oder Skips**, Core **2026.10.3/.4** mit
Plugins **0.13.374/.375**, Python **3.14.4**, Laufzeit **78,02 / 77,33 Sekunden**.
Die bestehenden Umgebungen wurden nicht neu installiert; Tests laden Repositoryquellen.
Das separat gebaute 0.2.11-Wheel enthält alle 23 Integrationsdateien bytegleich und
GPL-3.0-only einschließlich beider Lizenzkopien. Ruff und Dependencycheck erfolgreich.
Eine reguläre separate Zielinstallation desselben Wheels wurde mit der bestehenden
Core-.4-Abhängigkeitsumgebung außerhalb des Repository-Importpfads geprüft: Version
0.2.11, sieben native Modulimporte und alle 23 Paketdateien korrekt. Die ursprüngliche
Prüfumgebung wurde dabei nicht neu installiert.
JUnit und Paket-/Scopebelege: `artifacts/release-0.2.11/`.

Der erste native Vollreview wurde wegen begonnener Compaction im 256k-Default
verworfen. Eine separate kleine Transportprobe mit ausschließlich prozesslokaler
500k-Anforderung bestand anschließend den strikten nativen Abschluss-/Identitätsaudit;
die globale Konfiguration blieb bytegleich. Diese Probe ist ausdrücklich kein
Produktreview. Nach Ergänzung des eindeutigen Lizenzhinweises im Paket-Einstieg und
der prozesslokalen Kontextbindung bestanden die 138 Transporttests sowie erneut
alle 894 Core-.4-Tests (77,11 Sekunden). Das abschließende Wheel wurde neu gebaut
und separat regulär installiert; sein Inhalt wird vor dem neuen Vollreview geprüft.

Der zweite vollständige Review von Commit `32d1d0e` war transportgültig, aber
**blocked** mit einem hohen Befund AS-001: Wiederhergestelltes `off` galt als
Abregelungsfreigabe. Die Korrektur prüft beide Pfade gemeinsam und bindet Power an
die echte Freigabe einschließlich Attributwechsel. Auf ausdrücklichen Betreiberwunsch
bleibt die vorhandene Historie erhalten: Für die letzten Tage bestätigt er keine
Abregelung. Neue Zeilen erhalten eine eigene Kontrollprovenienz, alte bleiben in den
Diagnosen erkennbar. Keine rückwirkende technische Bestätigung der alten Signale.
Die genannten ersten Test-/Paketbelege gelten vor dieser Korrektur. Der korrigierte
Stand besteht je **900 Tests ohne Fehler oder Skips**, Core **2026.10.3/.4**,
Laufzeit **87,90 / 85,54 Sekunden**; Ruff und beide Dependencychecks erfolgreich.
Sein frisch gebautes Wheel wurde separat regulär installiert: sieben native
Core-.4-Importe, alle 23 Paketdateien bytegleich und GPL-Metadaten korrekt.
Wheel-SHA256: `792ba45f9c414c365d8ecbc9709cfed3b507838da9fca75c98c4c6d01b34fab9`.

Der neue Review muss alle sechs geänderten Forschungstexte und beide Lizenztexte
vollständig lesen; frühere Forschungsreferenzen werden nicht geerbt. Veröffentlichung,
aktuelle Sicherung, native HACS-Installation und HA-Rücklese erfolgen erst nach
akzeptiertem Review. Die folgenden Angaben dokumentieren die vorherigen gebundenen
Quellen und Betriebsnachweise, keine vorweggenommene Abnahme von 0.2.11.

## Freigegebener Stand vor 0.2.11

Stand: 26.10.2026. **Adaptive Solar 0.2.10 ist veröffentlicht und über HACS unter Core 2026.10.4 installiert.** Der gebundene Grok-4.7/high-Review ist ohne Findings abgeschlossen; GitHub-CI erfolgreich. Vier Anlageneinträge, native Einrichtung und installierte Paketbytes sind zurückgelesen. Ein qualifizierter produktiver ML-Fit und bessere Prognosegüte bleiben offen.

## Dokumentations- und Konsistenzpflege nach dem Release

Am 26.10.2026 wurden öffentliche [Installation](installation.md), [Bedienung](bedienung.md),
[Datenschutz](datenschutz.md) und [Entwicklung](entwicklung.md) ergänzt. Der HAOS-Weg
nennt nun Payloadvorbereitung, konkreten Core-User-Site-Pfad, Transfer, Prüfung und
Rückweg. Die Payloadvorbereitung mit den fünf unveränderten vorhandenen Musl-/Python-
Wheels wurde lokal offline ausgeführt; dies ist kein neuer Compilerlauf oder Deploy.

HACS beginnt jetzt beim ältesten geprüften Core 2026.10.2; eine ungenutzte veraltete
Versionskonstante entfällt. README und Entwicklungsschritte verwenden dieselben
Runtimepins wie CI. Der Horizont ist korrekt als einschließlich heute beschrieben.
Die sechs Forschungstexte wurden konsolidiert: unbelegte Fehlerbereiche, Ranglisten
und Prozentversprechen entfernt, Datenarten und Methoden mit direkten Primärquellen
verknüpft. Die frühere Breite der Literaturnotizen bleibt in der Git-Historie verfügbar.
Der Lizenzcommit `7f8d426` stellt eigene Inhalte unter GPL-3.0-only.

Frische Prüfung dieses Nachtrags: **893 Tests, null Fehler/Skips, 76,52 Sekunden** unter
Core **2026.10.3**, Testplugin **0.13.374**, Python **3.14.4**, pvlib **0.16.1** und
scikit-learn **1.9.1**. Ruff und `pip check` erfolgreich. Die übrigen Matrixarme wurden
hier nicht erneut ausgeführt. JUnit: `artifacts/documentation-audit-tests.xml`.
23 Markdown-Dateien mit vollständig geprüften lokalen Verweisen/Ankern, Tabellen und Codeblöcke
gerendert bzw. syntaktisch geprüft; 68 unterschiedliche verlinkte externe HTTP-Ziele
erreichbar. HTTP-Erreichbarkeit ist keine vollständige Inhalts- oder Tarifprüfung.
Versionsbezogene Primärdokumentationen und Quellen an den geänderten Aussagen ergänzen
diesen Linkcheck. Keine Zugangsdaten/private IPs in der Mustersuche über veröffentlichbare
Dateien gefunden; kein vollständiger Git-Historienscan behauptet.

Das nach der Pflege neu gebaute Wheel enthält alle 23 Integrationsdateien bytegleich
zum Arbeitsstand, einschließlich des Lizenztexts; GPL-3.0-only und die Lizenzkopie
in den Distributionsmetadaten sind geprüft. Die HAOS-Payloadvorbereitung enthält
nur die fünf vorgesehenen Distributionen samt Metadaten und gebündelten Bibliotheken,
keine überdeckenden NumPy-/SciPy-/Pandas-Pakete.

Diese Nachpflege enthält keine Änderung der Forecast-/Lernalgorithmen und keine
produktive HA-Aktion. Historische Release-, CI- und Grok-Angaben unten beziehen sich
weiterhin auf die eingefrorenen damaligen Quellen. Die neuen Forschungsbytes können
nicht mehr über die alten Forschungs-SHAs geerbt werden; ein neuer externer Review
oder eine Veröffentlichung dieses Nachtrags ist damit nicht behauptet.

## Update 0.2.10

Morgen-/Abenddämpfungen sind pro String in Modell und Einrichtung ergänzt, mit neutralen Altdefaults und Anwendung vor gemeinsamer AC-/DC-Begrenzung. Das bestehende Horizontmodell bleibt je String konfigurierbar. [AS-UI-001](geplante-updates.md) ist umgesetzt: neue Einträge mit einer Ausgangsstufe erzeugen ein Gerät; bestehende Gesamt-Sensoren bleiben unter ihren IDs als ausgeblendete Kompatibilitätsanzeigen am Einzelgerät erhalten. Mehrere Ausgangsstufen behalten Einzel- und Gesamtanzeigen. [Versionsinformationen](release-0.2.10.md).

Je **893 Tests ohne Fehler oder Skips** bestanden mit Core **2026.10.2/.3/.4**, Testplugins **0.13.373/.374/.375**, Python 3.14.4/glibc. Laufzeiten: **95,96 / 93,99 / 94,61 Sekunden**. Drei Kopien der bestehenden Prüfumgebungen wurden regulär mit demselben 0.2.10-Wheel installiert; ursprüngliche Umgebungen blieben unverändert. Isolierter Paketimport und sämtliche **22 Paketdateien einschließlich Markenbild** wurden außerhalb des Repositorypfads gegen den Wheel geprüft; `pip check` jeweils erfolgreich. Belege: `artifacts/compatibility-ha-2026.10.2-0.2.10-r2/` und entsprechend .3/.4.

Die Migrationstests prüfen AC/DC, mehrere Strings je Stufe, stabile Entity-/Unique-IDs und Benutzeranpassungen, native Energy-Ausgaben und unveränderte Messhistorie nach Reload sowie wiederholte Einzel-/Mehrfachstufenwechsel. Die Physiktests prüfen Dämpfungsgrenzen, Neutraldefaults, Zeitumstellungen, Mitternacht überschreitende Sonnentage, Polartag/-nacht und die Reihenfolge vor dem gemeinsamen Clip. Diese Nachweise ersetzen keine reale Genauigkeitsauswertung.

### Produktive Rücklese vom 26.10.2026

Die Veröffentlichung `v0.2.10` wurde nativ aus dem öffentlichen GitHub-Repository in HACS registriert und heruntergeladen; kein manueller Ersatz der ausgelieferten Komponentenbytes. Alle 22 Dateien stimmen mit dem geprüften Stand überein. Nach einer neuen geschützten Sicherung und einem Core-Neustart sind alle vier Einträge geladen. Drei Optionsflows übernahmen die passenden Open-Meteo-Horizont-/Dämpfungswerte; beim vierten Eintrag waren die entsprechenden Nullwerte bereits vorhanden. Die übrigen numerischen Einstellungen, Messbindungen und Energy-Präferenzen blieben erhalten.

Die Laufzeitrücklese bestätigt 80 unveränderte Entity-/Unique-IDs und Benutzeranpassungen bei vier Geräten statt acht. Alte Gesamtanzeigen bleiben als ausgeblendete Kompatibilitätsanzeigen am Einzelgerät. Die nächsten drei vollen lokalen Tage sind je Anlage vollständig, alle modellierten Leistungen innerhalb der nominellen Grenzen. Temperatur, Wind, Globalstrahlung und vorgesehene Leistungseingänge sind gültig; alle vier Anlagen melden Physik/kalt. HA-Konfiguration gültig, keine aktiven Repairs. Native GitHub-CI vor Installation auf Hauptbranch und Tag erfolgreich; die spätere Statusdokumentation ist von der eingefrorenen Implementierungsprüfung getrennt.

Bekannte nicht blockierende Hinweise: Core meldete die für 2027.10 angekündigte Abkündigung des verwendeten Geräte-Zuordnungszugriffs; die geprüften 2026.10-Versionen funktionieren. Eine bereits aus der Quellqualifikation bekannte MQTT-UTF8-Warngruppe trat beim Start erneut auf; nachfolgend sind alle benötigten Eingänge gültig. Es wird weder ein vollständig warnungsfreies Log noch die physische Zertifizierung der Quellen behauptet. Alte Komponentenbytes und die vier Historienstores vor der Korrekturübernahme sind zusätzlich lokal gesichert.

Die folgenden Abschnitte dokumentieren den historischen Stand 0.2.9 und dessen getrennte Nachweise.

Der erste vollständige Implementierungsreview der neuen Version fand zwei behebungsbedürftige Punkte: restaurierte Umweltsensor-/Leistungswerte im Nowcast und zusammengefasste Ablehnungsgründe kurzer beziehungsweise nicht prospektiver Trainingszellen. Beide sind in `8b40414` korrigiert und durch Regressionen abgedeckt. Der Featurevertrag v2 verwirft ältere unqualifizierbare Archivfeatures, erhält aber separat geprüfte Messintervalle und ausgegebene Tagesbeginn-Snapshots. Der erneute gebundene Grok-Review ist auf Commit `5a7da69` ohne Findings abgeschlossen; [Umfang und Hashbindung](review-findings.md).

## 1. Implementierung und Prüfung

[Verträge](implementation-contract.md), [Review](review-findings.md). Implementierung durch Subagenten mit hohem Aufwand.

**Implementierung 0.2.9:** optionaler generischer Messgültigkeitseingang für jede AC-/DC-Stufe. Ohne Bindung bleiben alte JSON-Daten und Fingerprints erhalten; gesetzte Quellen trennen die Messprovenienz. Physik und Umweltdaten bleiben bei Messausfällen verfügbar. [Messgültigkeitsvertrag und Grenzen](measurement-validity.md).

| HA Core | Testplugin | Bestandene Tests | Laufzeit |
|---|---|---:|---:|
| 2026.10.2 | 0.13.373 | 852 | 92,17 s |
| 2026.10.3 | 0.13.374 | 852 | 92,15 s |
| 2026.10.4 | 0.13.375 | 852 | 92,70 s |

Null Fehler/Skips; Python 3.14.4/glibc, normale 0.2.9-Wheel-Installation in getrennten Kopien der geprüften Umgebungen. Isolierter Import außerhalb des Repositories, alle 21 installierten Paketdateien und `pip check` je Umgebung geprüft; frühere Umgebungen erhalten. JUnit und Versions-/Hashbelege: `artifacts/compatibility-ha-2026.10.2-0.2.9/` (entsprechend .3/.4). Testextra nun Core .4/Plugin .375. Ruff grün.

26 neue Messgültigkeitsfälle; acht zusätzliche unabhängige native HA-.3-Gegenfälle ohne zwingende Findings. Zwölf native HA-.4-Integrator-/Template-Fälle umfassen elf normale Sicherheitsfälle und einen ausdrücklich reproduzierten `update_entity`-Gegenfall. Ein bestandener Gegenfalltest belegt die dokumentierte Grenze, keine Sicherheit dieses Pollpfads. Lokale Belege: `data/measurement-quality-audit-20261025/`, `data/integrated-source-validity-20261025/`. Keine produktive Ausfallinjektion.

Von sieben Kernmodulen ändert sich nur die Datenklasse um das optionale Feld; Physik-/Lernalgorithmen und Binärabhängigkeiten bleiben unverändert. ZIP und Wheel sind mit allen 21 Komponenten verglichen (`artifacts/package-source-validation-0.2.9.json`). Buildbackend setuptools 84.2.1 in isolierter Umgebung. Kein neuer Musl-Lauf und kein nativer produktiver 0.2.9-Fit behauptet. Grok-4.7/high-Implementierungsreview ohne Findings im gebundenen Commit `38c05d5`: 79 vollständige Originale und sechs unveränderte Forschungsreferenzen, keine Kontextkürzung; [Nachweis](review-findings.md).

Historische Stände bleiben getrennt: 0.2.8 je 814 Tests und positiver Implementierungsreview im gebundenen Commit `0285445`; 0.2.7 je 752 Tests und zuvor installierter Stand. Der ursprüngliche 231er-Musl-Nachweis betrifft die damalige Kernfassung, nicht die neue Datenklasse. Unveränderliche Quellen/Belege unter `artifacts/releases/0.2.7-reviewed/` und `artifacts/releases/0.2.8-implementation-20261025T132350Z/`.

## 2. Live-Stand und Grenzen

Freigegebene Aktivierung von 0.2.9: frisches geschütztes Konfigurations-/App-Backup ohne Recorder-Datenbank vollständig gelesen und gehasht; alle 21 neuen Integrationsdateien und drei betroffenen Konfigurationsdateien zurückgelesen. Altcode und ursprüngliche Timerdatei liegen außerhalb der aktiven HA-Lader. Binärabhängigkeiten wurden nicht ersetzt. Genau ein Core-Neustart, anschließend native Subentry-/Optionsflows mit Eintragsreloads.

Core 2026.10.4/Python 3.14.9, Konfiguration gültig, null aktive Repairs und vier geladene Entries mit Prognosekurven. Der vollständige unabhängige Readback umfasst 75 Prüfungen: vier erhaltene Sites, exakt neun erlaubte Bindungsänderungen, 21 Codehashes, drei Quellenhashes und zwei native MQTT-Gültigkeitskonfigurationen. Temperatur, Wind und Globalstrahlung werden verarbeitet; bei niedrigem Sonnenstand bleibt die GHI-Korrektur aus. Der Abregelungseingang bleibt erhalten. Eine visuelle Prüfung der Verwaltungsoberfläche ist damit nicht belegt.

Zwei Paket-Leistungskopien mit genau zwei Recorder-Ausnahmen und zwei Gültigkeitssignale sind aktiv. Für die Originalintegrale ist eine Minute als maximales Teilintervall konfiguriert; fortschreitende Berichtszeiten bei unveränderten Nachtwerten und angenommene Null-Deltas sind nativ beobachtet. Die tatsächlichen Timer unterliegen der HA-Ereignisplanung. Der lokale Konfigurationsreview durch Grok 4.7/high hat nach drei Dokumentationskorrekturen im Kandidaten `439373b` keine Findings. Empfangs-TTL, Retain-/Cachepoll-Grenzen und bestehender Quellendrift bleiben dokumentierte Betriebsannahmen; dies ist keine physikalische Vollqualifikation.

Die freigegebenen Lernquellen sammeln neue Originalintervalle. Ein bewusst nur mit Leistung angebundener Eintrag erhält keine Energielabels. Alle Modelle benötigen weiterhin ausreichende qualifizierte Historie; es ist kein produktiver ML-Fit oder Genauigkeitsvorsprung belegt. Betreiberangabe ungedrosselten AC-Betriebs verlangt keine Herstellerdiagnostik. Hardwareunabhängige Schnittstellen sind keine Genauigkeitszusage. Die aktuellen privaten Aktivierungs-/Readbackbelege liegen unter `data/activation-0.2.9-20261025/` und werden nicht veröffentlicht. Dieser Statusnachtrag ergänzt die geprüften Quellstände um aktuelle Betriebsnachweise und verändert keinen Modellcode.

Keine Energy-Umschaltung und kein dauerhafter Vergleichsjob. Die gesondert freigegebenen West-Referenzen wurden auf dieselbe Ausgangsgrenze angeglichen. Ein erster prospektiver Einmal-Capture enthält ausschließlich künftig vollständige gemeinsame Stunden; er gehört nicht zur vorab festgelegten Hauptkohorte. Ein lokaler90-Tage-Walk-forward mit60 Tagen Anlauf und30 Auswertungstagen ist abgeschlossen. Er verwendet nachträglich beschaffte ursprüngliche Wetterläufe und angenommene Verfügbarkeitszeiten; Messqualifikation und vollständige lernende Helios-Referenz fehlen. Er ist bedingte historische Diagnose, kein produktiver oder prospektiver Genauigkeitsnachweis. Private Parameter/Ergebnisse bleiben außerhalb Git/Review. [HAOS-Bauweg](haos-installation.md), [Messplan](validierung.md): mindestens30 vollständige gepaarte Tage je Stratum. Kein belegter Vorsprung gegen beide Referenzen.

## 3. GitHub-Erstveröffentlichung

Die dokumentierte Erstveröffentlichung stellte Quellstand **0.2.8**, Dokumentation, Tests, Recherche und Logo unter [togo42/Adaptive-Solar](https://github.com/togo42/Adaptive-Solar) bereit. Sie änderte keine produktive HA-Installation. Der anschließend gültig abgeschlossene Implementierungsreview bindet Commit `0285445`, 76 vollständige Originale und sechs unveränderte Forschungsreferenzen; Umfang und Grenzen stehen im [Reviewnachweis](review-findings.md). Die lokale Aktivierung von 0.2.9 ist keine neue Veröffentlichung.

Vorprüfung dieser Erstveröffentlichung: **758 Tests bestanden**, null übersprungen, 66,75s; Ruff und `pip check` erfolgreich. Der JUnit-Bericht liegt lokal unter `artifacts/github-preflight-tests.xml`. GitHub Actions führt die vorhandene Testsuite nach dem Push separat aus.

Die genannten `artifacts/`- und `reviews/private/`-Pfade bezeichnen lokale, ausgeschlossene Nachweise. Diese Dateien und private Installationsparameter sind im öffentlichen Repository nicht enthalten.
