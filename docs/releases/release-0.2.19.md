# Adaptive Solar 0.2.19

Dieses Wartungsrelease ersetzt die veraltete Geräte-Eigentümerabfrage
`DeviceEntry.config_entries` durch `config_entry_id`. Die Gerätebereinigung
behält ihre bisherigen Grenzen: nur eigene, nicht mehr benötigte Geräte ohne
verbliebene Entitäten werden entfernt.

Services und ihre Tests importieren `probatio` direkt. Der bisherige
`voluptuous`-Import war durch HAs Kompatibilitätsshim unterstützt; die Änderung
beseitigt eine uneinheitliche Importkonvention. Der Referenzdienst initialisiert
seine Empfangszeit jetzt explizit. Antworten werden weiterhin vor ihrer
Validierung gestempelt; Fehler ohne Antwort erhalten einen UTC-Zeitstempel.

## Upgrade und Rückweg

Vorhandenen Komponentenstand sichern, in HACS 0.2.19 herunterladen und einmal
Home Assistant Core neu starten. Vorhandene Einträge und Optionen weiterverwenden;
anschließend Eintragsstatus, Entity-IDs, Prognosen, Konfigurationsprüfung und Repairs
kontrollieren. Ein Core-/OS-Upgrade oder neuer Binärabhängigkeitsbau ist nicht nötig.

Konfiguration, Storeformate, Physik, Lerngates und Abhängigkeitspins ändern sich
nicht. Für den Code-Rückweg die gesicherten Komponentenbytes oder HACS 0.2.18
verwenden und Core neu starten. Lernstores bleiben erhalten; interne
`.storage`-Dateien nicht direkt zurückschreiben. Dashboardressourcen und externe
Archivhostdienste werden durch dieses HACS-Update nicht geändert.

## Prüfung und Grenzen

Der Implementierungsstand `8dbf980` bestand lokal 1.729 Tests ohne Skips unter
HA Core 2026.10.4 / Python 3.14 sowie Ruff und `pip check`. Die vorhandenen
nativen HA-Tests prüfen unter anderem Gerätewechsel mit Erhalt der Entity-IDs,
Servicevalidierung sowie Providerfehler und Timeouts. Releaseversionen und
Dokumentation sind zusätzliche Metadatenänderungen.

Für diesen Wartungsstand wurde kein neuer externer Review durchgeführt. Frühere
Reviewreceipts gelten ausschließlich für ihre gebundenen Quellen. Veröffentlichungs-,
CI- und Buildnachweise stehen in den [Prüfnachweisen](../entwicklung/pruefnachweise.md);
anlagenspezifische Laufzeitprotokolle bleiben privat. Die Prüfungen belegen keine
höhere reale Prognosegenauigkeit.

## Veröffentlichung und Laufzeitprüfung

`v0.2.19` wurde aus Releasecommit
`de9c832da394b7d6b0ebeb041a73cad274012224` veröffentlicht. Main-/Tag-CI bestanden
jeweils mit 1.729 Tests ohne Skips und erfolgreichem HA-freiem Archivhostjob.
Die vier Releaseartefakte wurden nach Download bytegleich geprüft.

Die native HACS-Installation mit einem Core-Neustart auf bestehendem
HAOS / Core 2026.10.4 wurde mit Datei- und Laufzeitreadbacks kontrolliert.
Einträge, Entity-IDs, Optionen, kompatible Historien und Tagesbeginnwerte blieben
erhalten; neue Prognosen tragen die Releaseprovenienz. Konfiguration und Repairs
wurden geprüft. Private Einzelbelege werden nicht veröffentlicht.
