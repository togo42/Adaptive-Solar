# Adaptive Solar 0.2.21

Stand: 02.11.2026, **veröffentlicht als v0.2.21** auf Commit
`2dd940c3aa1a00d7291228f24ebaac90b56eef14`.
[GitHub-Release und Pakete](https://github.com/togo42/Adaptive-Solar/releases/tag/v0.2.21).

## Änderungen

Die optionalen [Speichersparprofile](../archiv/speichersparprofile.md) trennen
drei Entscheidungen:

- Der externe Archivhost kann Recorder-Istwerte und Quellenqualität alle sechs
  UTC-Stunden aufnehmen, Referenzprognosen weiterhin stündlich. Neue Jobs und
  Timervorlagen heißen `actuals` und `references`; der bisherige kombinierte
  `observations`-Job bleibt kompatibel nutzbar. Der HA-Abholtimer bleibt bei fünf
  Minuten. Vorhandene Timer werden durch die neuen Dateien nicht umgestellt.
- `quality_diagnostics: "compact"` speichert nach derselben vollständigen
  Qualitätsprüfung einen ausdrücklich reduzierten Bericht. Rohwerte, Masken,
  Stundenentscheidungen, Gegenbelege, Pins und echte Zeitstempel bleiben erhalten;
  große Ereignisreferenzlisten werden durch Anzahl und Hash ersetzt. Die
  Detailarrays lassen sich aus den Hashes allein nicht rekonstruieren.
  Standard ohne Auswahl bleibt `full`; alte Captures bleiben lesbar. Die
  unveränderte 32-MiB-Grenze gilt für den tatsächlich archivierten Capture.
- Die separate HA-Option `archive_source_report_profile: night_sparse_v1`
  reduziert ausgewählte unveränderte Nacht-Rohdiagnosen. Messung, Sensorreporting,
  Lernen, Energie-/Kontroll-/Messgültigkeitsberichte und `qualified_interval`
  bleiben vollständig. Prognosen für den nächsten Tag werden nachts weiter
  archiviert. SPA-Nachtfenster werden einmal je lokalem Tag im Executor mit
  90 Minuten Schutz an beiden Tagesrändern berechnet; unsichere Fenster und
  Exportfehler erhalten die vollständige Aufnahme. Standard bleibt `full`.

Außerdem enthält diese Version zwei zuvor getrennt vorbereitete Hostkorrekturen:

- Die fortlaufende Qualitätsauswahl validiert vollständige Forecastoriginale,
  hält für Konfigurationsprüfungen aber nur kompakte interne Belege statt aller
  wachsenden Forecastpayloads. Gegenbelege und ursprüngliche Originalhashes
  bleiben erhalten; Ereignis-, Arbeits- und Ausgabegrenzen werden nicht erhöht.
- Der HA-Collector bestätigt einen festen, aus der ersten Exportantwort
  belegten Journalstand. Später eintreffende Ereignisse verschieben diesen
  Stand nicht. Ganze Seiten werden vor dem Abschluss unverändert dauerhaft
  archiviert. Fehlende Grenzmetadaten verwenden weiterhin eine leere
  Abschlussseite; Lücken, Producerfehler, offene Schreibvorgänge und ein vor
  Abschluss erreichtes Seitenlimit bleiben Fehler.

Physik, native Lerngates, Messgrenzen, HA-Storeformate und Abhängigkeitspins werden
durch diese Profile nicht verändert. Ein reduzierter Diagnosestrom ist kein
vollständiger Reportkadenz- oder Verfügbarkeitsnachweis. Weniger gespeicherte
Qualitätsdetails bedeuten keine geringere vollständige Ableitungsarbeit und
keine automatische physische Quellenqualifikation.

## Upgrade und Rückweg

Für das HA-Update den bisherigen Komponentenstand und die vorhandenen Optionen
sichern, 0.2.21 über HACS herunterladen und Core einmal
neu starten. Bestehende Einträge weiterverwenden; anschließend Einträge,
Entity-IDs, Optionen, Historiendaten, Prognosen, Konfiguration und Repairs prüfen.
Das Nachtprofil wird erst durch eine ausdrückliche Optionswahl aktiv. Es liegt
außerhalb der Anlagenphysik und verändert deren Fingerprint nicht.

Der neue HA-Code hat einen neuen Producerquellhash. Bestehende historische
Quellenbindungen dürfen nicht auf diesen Hash umgeschrieben werden. Für neue
Zeiträume sind passende neue Producer-/Konfigurationsbelege erforderlich.

Ein HACS-Update installiert keine externen Hostdienste und ändert keine
Archivtimer. Der Host benötigt einen eigenen geprüften Release-/Runtimewechsel.
Für die Streamtrennung den alten Beobachtungstimer zuerst deaktivieren und einen
laufenden Dienst auslaufen lassen; beide neuen Timer erst nach kontrollierten
Aufnahmen und Readback aktivieren. Gemeinsame und getrennte Beobachtungstimer
nicht parallel betreiben. Ablauf und Rückweg stehen in der
[Hostinstallation](../archiv/archiv-host-installation.md).

Für den HA-Code-Rückweg den gesicherten Komponentenstand oder 0.2.20 verwenden
und Core neu starten. Einträge, kompatible Lernstores und Tagesbeginnwerte
erhalten; keine direkten `.storage`-Änderungen. Hostrückweg und HA-Rückweg sind
getrennt. `full` erfasst künftig wieder vollständige Diagnosen, stellt aber
bewusst ausgelassene Zwischenreports nicht nachträglich her. Vorhandene
Originale, Pins und fortgeschriebene Checkpoints werden nicht zurückgesetzt.

## Prüfung und Veröffentlichungsgrenzen

Der Funktionsstand `d25e9b42f9943a880dd306471d1648b0cdadf158` enthält den
Collectorfix `c7aea3f` und die Qualitätskontextkorrektur `7760cd6`. Seine lokale
Vollsuite bestand unter **Core 2026.10.4 / Python 3.14 mit 2.453 Tests ohne
Skips bei 91,05 % kombinierter Zeilen-/Zweigabdeckung** und unverändertem
90-%-Gate. Die 23 bestehenden SQLite-ResourceWarnings bleiben vorhanden.
Ruff, `pip check`, HA-freie CLI-Prüfungen sowie unabhängige gezielte
Code-/Verhaltensreviews sind in den
[Speichersparprofilen](../archiv/speichersparprofile.md#lokale-prüfung-des-vorbereiteten-stands) eingeordnet.
Die Releasevorbereitung ändert daran Versionsmetadaten und öffentliche
Status-/Releasehinweise; sie ist kein neuer externer vollständiger Quellreview.

Der genaue Releasecommit bestand erneut die lokale Vollsuite mit 2.453 Tests
und 91,05 % Coverage. Die CI für [main](https://github.com/togo42/Adaptive-Solar/actions/runs/41508881355)
und [v0.2.21](https://github.com/togo42/Adaptive-Solar/actions/runs/41508881427)
bestand einschließlich nativer HA-Tests und separater HA-freier Hostinstallation.
Alle 42 Komponentendateien stimmen zwischen Quellstand, Wheel, sdist und
Integrations-ZIP überein. Eine frische reguläre Wheelinstallation bestand
Abhängigkeitsprüfung und 35 Modulimporte. Alle vier veröffentlichten Assets
wurden erneut heruntergeladen und ihre SHA256-Werte verglichen. Das ZIP enthält
die Komponenten-Dateien direkt an seiner Wurzel, einschließlich `manifest.json`
und `LICENSE`. ZIP-SHA256:
`ad4f726850fff4246b01d326dcbb97a2ed001a0a7026b68ac27aa38c2d86e701`.

Diese Prüfungen und einzelne Größenproben belegen weder langfristige
Speicherkapazität noch einen Prognosevorsprung, einen produktiven ML-Fit oder
eine physische Quellenqualifikation. Die folgende Installationsprüfung ist
ein eigener, begrenzter Laufzeitnachweis.

## Installation und Erhaltungsprüfung

Am 02.11.2026 wurde 0.2.21 über natives HACS installiert und mit genau einem
Core-Neustart unter unverändertem **Core 2026.10.4** aktiviert. Eine geschützte
native Konfigurations-/SSL-Sicherung ohne Recorderdatenbank sowie eine gezielte
Komponenten-/Historienkopie wurden vorher geprüft. Ein Restore wurde nicht getestet.
Alle 42 installierten Komponentendateien stimmen mit dem Versionstag überein.

Die vier bestehenden Einträge wurden weiterverwendet und anschließend über ihre
native Optionsverwaltung auf `night_sparse_v1` gestellt. Ausschließlich dieses
Optionsfeld durfte abweichen. Die übrigen Optionen, Anlagen-/Messzuordnungen,
80 Entity-/Unique-IDs, vier Geräte, acht Stores, Historienfingerprints,
vorab abgegrenzte abgeschlossene Messintervalle und Tagesbeginnwerte einschließlich
Kurven und Provenienz blieben erhalten. Ebenso unverändert sind Energy- und Dashboardzuordnungen.

Die Laufzeitprüfung bestätigte gültige Eingänge und drei vollständige Folgetage
je Anlage, HACS ohne ausstehendes Update, gültige Konfiguration und keine aktiven
Repairs, Adaptive-Solar-Laufzeitfehler oder blockierenden Startaufrufe. Vier neue
Originalprognosen tragen den passenden Producerquellhash. Für zwei der vier Quellen wurde
bereits ein neues Messintervall an diesem Hash geprüft; für die übrigen wurde
kein künstlicher Messwert erzeugt. Historische Pufferverdrängung bleibt als
Producerstatus sichtbar; sie belegt keine neue Collectorlücke.

Private Belege: `data/release-0.2.21-20261102/runtime-audit-final.json` und
`additional-audit-final.json`. Diese Prüfungen belegen Softwareherkunft und
Erhaltung beim Update; sie qualifizieren keine physische Messquelle und zeigen
keinen Prognosevorsprung. Ein vollständiges Tag-/Nachtfenster zur Messung der
tatsächlichen Einsparung steht nach der abendlichen Aktivierung noch aus.
