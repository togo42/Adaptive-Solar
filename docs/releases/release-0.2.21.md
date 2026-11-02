# Adaptive Solar 0.2.21

Stand: 02.11.2026, **lokaler Releasekandidat**. Veröffentlichung, Release-CI,
Downloadprüfung und produktive Installation sind noch nicht abgeschlossen.
Zuletzt veröffentlicht ist [0.2.20](release-0.2.20.md).

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
sichern, nach Veröffentlichung 0.2.21 über HACS herunterladen und Core einmal
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

Die vorhandene CI führt Python-3.14-/native HA-Tests mit Coverage sowie eine
separate HA-freie Archivhostinstallation aus. Abgeschlossene CI älterer Commits
ersetzt keinen Lauf des späteren Releasecommits. Wheel, sdist,
Integrations-ZIP und SHA256SUMS sind aus genau diesem Releasecommit zu bauen,
auf vollständige öffentliche Komponentenbytes zu prüfen und nach Veröffentlichung
erneut herunterzuladen. Das Integrations-ZIP enthält die Komponenten-Dateien
direkt an seiner Wurzel, einschließlich `manifest.json` und `LICENSE`.

Diese Prüfungen und einzelne Größenproben belegen weder langfristige
Speicherkapazität noch einen Prognosevorsprung, einen produktiven ML-Fit oder
eine erfolgreiche spätere Installation. Ein tatsächlicher HA-/Hostreadback
wird erst nach Durchführung separat dokumentiert.
