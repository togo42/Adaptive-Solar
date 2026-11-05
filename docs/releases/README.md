# Adaptive Solar: Versionshinweise

Veröffentlicht: **[0.2.24](release-0.2.24.md)** mit ausschließlich lesender Diagnose
aller aktuell gespeicherten Schattenfenster je Stufe.
**Installation und Produktivabnahme stehen noch aus; HA bleibt auf 0.2.23.**
Der unveränderliche Tag bindet `f21ad29c8341f9d784e686b4a74ab9a6a4097c93`;
alle vier öffentlichen Assets sind bytegleich geprüft, die Main-CI ist erfolgreich.
Branch-/Tag-CI sind hier noch nicht abschließend belegt. Historische
Vorbereitungsergebnisse für `9c9a709` bleiben getrennt.

Veröffentlicht und über Marketplace installiert: **[0.2.23](release-0.2.23.md)** mit automatischer HA-nativer
ML-Paketlieferung nach Core-Containerwechsel und aktuellem Marketplace-Installationsweg.
Die begrenzte Produktivabnahme und Wiederherstellung der ursprünglichen
Archivtimer sind abgeschlossen; neue externe Quellenfreigaben bleiben getrennt.

Historischer Vorgänger: **[0.2.22](release-0.2.22.md)**
mit Korrekturen der unabhängig geprüften Grok-Befunde. Releaseartefakte und die
begrenzte Adaptive-Solar-Erhaltung sind geprüft. Nach dem zwischenzeitlichen
Neustart bestätigt eine frische Folgeprüfung gültige Konfiguration, erhaltene
Daten und keine offenen Repairs. Der separate Archivhoststand `f1c7d9b` wurde
bereits abgenommen.

Die historische **[0.2.21](release-0.2.21.md)** bleibt mit ihrer damaligen
[Quellabnahme und Releaseprüfung](release-0.2.21.md#prüfung-und-veröffentlichungsgrenzen)
erhalten. Review, Tests und Artefakte gelten ausschließlich für die jeweiligen Quellstände.
Die Hinweise beschreiben Änderungen und den Upgradepfad der jeweiligen Version.
Historische Testzahlen gelten ausschließlich für den damals geprüften Quellstand;
siehe [Prüfnachweise](../entwicklung/pruefnachweise.md).

| Version | Schwerpunkt |
| --- | --- |
| [0.2.24](release-0.2.24.md) | Veröffentlichter additiver lesender Schattenfenster-Snapshot; Installation und Produktivabnahme ausstehend |
| [0.2.23](release-0.2.23.md) | HA-native ML-Paketlieferung und Marketplace-Installation |
| [0.2.22](release-0.2.22.md) | Setuprollback, harte Snapshotcaps, belegte Replayphasen sowie Qualitäts-/Archivkorrekturen |
| [0.2.21](release-0.2.21.md) | Kompakte Qualitätsdiagnosen, getrennte Archivintervalle, optionales Nachtprofil und begrenzte Collectorläufe |
| [0.2.20](release-0.2.20.md) | Offline-Support-Guard, optierte Istwert-Quellenbindung und Aufnahme-/Zeitkorrekturen |
| [0.2.19](release-0.2.19.md) | Aktuelle HA-Geräte-API und explizite Servicevalidierung/-Empfangszeit |
| [0.2.18](release-0.2.18.md) | Gespeicherte Tagesbeginn-Stundenkurven und Archivhelfer |
| [0.2.17](release-0.2.17.md) | Strenger Replay mit begrenzter Rechenrundungstoleranz |
| [0.2.16](release-0.2.16.md) | Originaldatenexport und externer Archivbetrieb |
| [0.2.15](release-0.2.15.md) | Messkontinuität, Shadowkandidaten und Vergleichsarchive |
| [0.2.14](release-0.2.14.md) | Nachtstrahlung und historische Tagesstartwerte |
| [0.2.13](release-0.2.13.md) | Messabdeckung und Ablehnungsdiagnose |
| [0.2.12](release-0.2.12.md) | Gelernte Direktstrahl-Verschattung |
| [0.2.11](release-0.2.11.md) | Lizenz, öffentliche Anleitungen und Abregelungsprüfung |
| [0.2.10](release-0.2.10.md) | Stringdämpfung und Anzeige-Migration |

Downloads und unveränderte ältere Tags stehen unter
[GitHub Releases](https://github.com/togo42/Adaptive-Solar/releases).
Installation und Prüfung der eigenen Anlage folgen der
[Installationsanleitung](../anwendung/installation.md).
