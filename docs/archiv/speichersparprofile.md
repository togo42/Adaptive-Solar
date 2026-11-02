# Sparsamere Archivierung vorbereiten

Stand: 02.11.2026, vorbereiteter Entwicklungsstand, noch keine Release- oder
Betriebsfreigabe. Die normalen Prognosen und das aktive Lernen benötigen nicht
die gesamte optionale Langzeitdiagnostik. Dieses Profil reduziert deren Umfang,
ohne Messintervalle, Lernschwellen oder echte Empfangszeiten umzudeuten.

## Drei getrennte Stellschrauben

| Bereich | Vorbereitetes Profil | Bewusste Einschränkung |
| --- | --- | --- |
| Istwerte und Quellenqualität | Eigener `actuals`-Job alle sechs UTC-Stunden, weiterhin 72 Stunden Rückblick | Korrekturen werden später beobachtet; zwischenzeitliche Revisionen können fehlen |
| Referenzprognosen | Eigener `references`-Job stündlich | Neuer geplanter Abrufzeitpunkt Minute 24 UTC; damit können sich die erfassten Stände ändern |
| Qualitätsdiagnostik | `quality_diagnostics: "compact"` im Hostprofil | Große Listen einzelner Belegreferenzen werden nicht erneut gespeichert |
| Zusätzliche Nacht-Rohdiagnostik | Option `archive_source_report_profile: night_sparse_v1` in HA | Keine vollständige Folge unveränderter, nichtkritischer Nachtmeldungen |

Die Einstellungen sind voneinander unabhängig. Vorhandene Konfigurationen bleiben
bei voller Diagnostik; neue Vorlagen sind kein Auftrag zur produktiven Aktivierung.
Der HA-Abholtimer bleibt bei fünf Minuten. Er transportiert bereits erzeugte
Ereignisse: Selteneres Abholen ersetzt keine Reduktion ihrer Erzeugung und kann
den begrenzten Exportpuffer überlaufen lassen.

## Qualitätsberichte: Entscheidungen statt wiederholter Listen

`--quality-diagnostics compact` greift erst **nach** der unveränderten vollständigen
Qualitätsprüfung. Es bleiben insbesondere erhalten:

- originale Recorderantwort, normalisierte Istwerte und vollständige Qualitätsmasken;
- Stundenentscheidungen mit Abdeckung, Ablehnungsgründen und Gegenbelegen;
- Quellenbindungen, erkannte Konfigurationskonflikte, Policy- und Implementierungsbezug;
- ursprüngliche Empfangszeit sowie echte `as_of`-, Erstellungs- und Validierungszeiten.

Die großen Ereignis- und Konfigurationsreferenzlisten sowie die Ereignislisten
je Stunde werden durch Anzahl und Prüfsumme ersetzt. Ein eigenes Berichtschema
kennzeichnet diesen geringeren Diagnoseumfang. Die Prüfsumme des Vollberichts
ist eine Inhaltsbindung, keine komprimierte Kopie: Aus einem Hash lässt sich
der ausgelassene Inhalt nicht wiederherstellen. Eine spätere vollständige
Nachprüfung braucht weiterhin die passenden Originale, Policy und Implementierung.
Ein kompakter Bericht allein ist kein vollständiges Belegpaket.

Damit entstehen weder ein zusätzlicher Objektspeicher noch neue gegenseitige
Dateireferenzen. Alte Aufnahmen bleiben unverändert lesbar. Das unveränderte
32-MiB-Limit gilt für den tatsächlich archivierten Capture; die vollständige
Ableitung hat weiterhin ihre eigenen Ressourcenbegrenzungen. Weniger Speicherung
bedeutet deshalb nicht automatisch weniger Rechenarbeit.

Der Standard ohne explizite Auswahl bleibt `full`. Die lokale Ableitung mit
`continuous_quality.py` erzeugt weiterhin vollständige Berichte für gezielte
Diagnosen. Details: [Istwert-Qualitätsadapter](istwert-qualitaetsadapter.md).

## Nacht: weniger zusätzliche Wiederholungen

`night_sparse_v1` betrifft ausschließlich den optionalen Export zusätzlicher
Rohberichte. Sensorreporting, Recorder, native Energieverarbeitung, Lernen und
`qualified_interval` bleiben erhalten. Energie-, Abregelungs- und
Messgültigkeitsquellen werden auch nachts vollständig exportiert.

Reduzierbar sind unveränderte numerische Null-Leistungsberichte sowie unveränderte
numerische Einstrahlungs-, Temperatur- und Windberichte. Zustands-, Einheiten-
und Gültigkeitswechsel bleiben sichtbar; ein echter neuer Bericht wird mindestens
stündlich als Diagnoseprobe durchgelassen. Ohne neue Meldung entsteht kein
künstlicher Heartbeat und insbesondere kein erfundener Nullwert.

Die Nachtgrenzen werden aus dem Anlagenstandort berechnet, mit 90 Minuten Schutz
um Sonnenauf- und -untergang. Fehlt eine verlässliche Nachtgrenze, bleibt die
volle Aufnahme aktiv. Das schützt auch Tagesrandstunden, deren vollständige
Messunterstützung vor dem Sonnenaufgang beginnen kann.

Das Profil und die Zahl ausgelassener Wiederholungen sind diagnostisch sichtbar.
Aus dem reduzierten Strom lässt sich später keine vollständige sekundenweise
Reportfrequenz oder lückenlose Verfügbarkeit dieser Diagnosequellen beweisen.
Nachts ausgegebene Prognosen für den kommenden Tag werden weiter archiviert.

## Aufbewahrung und Rückweg

Diese erste Stufe reduziert zukünftige Daten bereits bei ihrer Aufnahme. Sie
führt **keine** neue Löschfrist für bestehende Nachtwerte ein. Bestehende
Originalseiten können mehrere Ereignisarten enthalten; eingefrorene Datasets und
Replayabhängigkeiten bleiben deshalb unverändert. Die bisherige Wartung nach
24 Kalendermonaten und der Schutz gepinnter Originale gelten weiter.

Eine gesonderte kurze Detailhaltung kann später ergänzt werden, wenn nach der
Messung des reduzierten Betriebs noch ein Bedarf besteht. Sie ist keine
Voraussetzung für diese Einsparung. Ein zusätzliches Archiv mit eigener
Löschlogik wird dafür jetzt nicht aufgebaut.

Für den Rückweg `quality_diagnostics` und das HA-Rohreportprofil auf `full`
stellen; bei Bedarf die getrennten Timer wieder durch den bisherigen
`observations`-Timer ersetzen. Nie beide Timerkombinationen parallel betreiben.
Der Rückweg erfasst wieder mehr zukünftige Daten, rekonstruiert aber keine zuvor
bewusst ausgelassenen Diagnosemeldungen oder Zwischenrevisionen.

## Vor einer späteren Aktivierung

Zuerst bereits laufende, eingefrorene Auswertungen abschließen. Danach Host- und
HA-Änderung getrennt aktivieren und prüfen: Die Hoständerung benötigt keinen
HA-Neustart. Das Nachtprofil benötigt die vorbereitete HA-Version und eine
explizite Optionsänderung. Ein neuer HA-Quellstand hat einen neuen Producerhash;
historische Quellenbindungen dürfen nicht stillschweigend auf ihn umgeschrieben
werden. Neue Zeitabschnitte müssen passend geprüft und gebunden werden.

Die [Hostinstallation](archiv-host-installation.md) beschreibt Timerwechsel und
Rückweg. Nach Aktivierung mindestens ein vollständiges Tag-/Nachtfenster
beobachten: neue komprimierte Originalbytes je Quelle, Dateiblockbelegung,
Capturegröße, erfolgreiche Transfers, echte Zeitstempel und Qualitätsentscheidungen.
Größenvergleiche einzelner Probecaptures sind kein gemessener Tagesverbrauch und
keine Zusage für die langfristige Kapazität.

## Lokale Prüfung des vorbereiteten Stands

Am 02.11.2026 bestanden 2.453 Tests mit tatsächlichem HA Core, ohne Fehler oder
Skips, bei 91,05 % kombinierter Zeilen-/Zweigabdeckung und unverändertem 90-%-Gate.
Die 23 bereits bestehenden SQLite-ResourceWarnings sind weiterhin vorhanden.
Ruff, Abhängigkeitsprüfung und die beiden betroffenen Host-CLI-Imports mit
gesperrtem HA bestanden ebenfalls.

Drei GPT-6.1-Sol/high-Subagenten bearbeiteten die getrennten Bereiche; die
Host-/Qualitätsänderungen und das Nachtprofil wurden zusätzlich jeweils von
einem anderen Subagenten geprüft. Ein gefundener Randfall bei fehlenden
Sonnenereignissen eines Nachbartags am Polarübergang ist korrigiert und durch
einen Regressionstest abgedeckt. Beide Zeitumstellungen, die unveränderte
Verfügbarkeit positiver und negativer Qualitätsrevisionen, volle Standardprofile
und Fehlerfälle gehören zum Prüfungsumfang.

Das ist eine lokale Implementierungsprüfung mit begrenztem unabhängigen Review,
kein externer vollständiger Quellreview, keine Produktivabnahme und kein Beleg
einer besseren Solarprognose. Die abschließenden Testartefakte liegen lokal unter
`artifacts/storage-reduction-tests.xml` und `artifacts/storage-reduction-coverage.json`;
private Größenproben und Betriebsbelege gehören nicht in den öffentlichen Quellumfang.
