# Adaptive Solar 0.2.16

## Änderungen

- Optionaler HA-Puffer für ursprüngliche Wetterantworten, Beobachtungen,
  Konfiguration, ausgegebene Prognosen und tatsächlich verwendete Lernzustände.
  Passive Rohberichte und angenommene wie abgelehnte Schattenlernschritte
  ermöglichen kausale Vergleiche späterer Modelländerungen.
- Externes Archiv mit unveränderlichen Originaldateien, Prüfsummen und
  wiederaufbaubarem SQLite-Index. Aufbewahrung: 24 Kalendermonate; eingefrorene
  Datensätze bleiben geschützt. PostgreSQL bleibt eine spätere Abfrageoption.
- Separate Aufnahme regionaler Kurzfristmodelle, länger reichender Modelle und
  echter Wetterensembles. Energiequantile entstehen aus vollständigen
  Mitgliedsverläufen; fehlende Prognoseabdeckung wird nicht aufgefüllt.
- Originalreplay und getrennte Kandidatenvergleiche für Physik, Wettermodelle
  und chronologisches Schattenlernen. Die Mess-, Physik- und Lernkorrekturen
  aus 0.2.15 bleiben erhalten; erfolgreiche Fits und Physikfallbacks sind im
  Replay unterscheidbar. Der frühe Bias-Kandidat bleibt ein separater Shadow-Arm.
- Hostdienste für regelmäßige HA-, Wetter- und Recorderaufnahme mit
  verschlüsselter Credentialbereitstellung, Platzprüfung und Statusbelegen.
- Kalter Wetter-/Physikimport über den nativen HA-Importexecutor statt im
  Eventloop (AS-START-001).

Details: [Archivbetrieb](archivbetrieb.md), [Datenvertrag](archive-storage-contract.md),
[Hostinstallation](archiv-host-installation.md),
[Modellauswahl](wettermodelle-und-prognosehorizonte.md).

## Upgrade von 0.2.15 und Rückweg

Runtimepins bleiben pvlib 0.16.1 und scikit-learn 1.9.1; kein Core-/OS-Upgrade.
Nach dem HACS-Download Core einmal neu starten. Vorhandene Optionen,
Entity-/Unique-IDs, Geräte, Energy-Zuordnungen und gültige Historie werden
weiterverwendet. Zusätzliche Physik-/Nowcastoptionen behalten ihre Werte.

`archive_export` ist standardmäßig aus und gehört nicht zum physikalischen
Historienhash. Das Einschalten setzt die Lernhistorie nicht zurück. Der
vollständig abgeschlossene Optionsflow lädt den Eintrag neu; erst ein
eingerichteter externer Collector überträgt Daten zum Archivhost.

Vorher Komponente, Lern-/Vergleichsstores und Optionen sichern. Bei Exportproblemen
kann der Hostcollector gestoppt und die Exportoption ausgeschaltet werden.
Eine Rückkehr zu 0.2.15 erfolgt über HACS und einen Core-Neustart; die gezielte
Sicherung bleibt für einen notwendigen Datenrückweg erhalten. Externe Originale
und der HA-Puffer werden durch Abschalten oder Code-Rückkehr nicht gelöscht.

## Aussagegrenzen und Nachweise

Archivierung und erfolgreicher Replay belegen reproduzierbare Eingaben und
Berechnungen. Sie belegen weder bessere Prognosen noch kalibrierte
Ensemblewahrscheinlichkeiten. Dafür sind zeitlich getrennte, qualitätsgeprüfte
Istwerte und eine lokale Auswertung erforderlich. Beim Schattenreplay werden
Sitzungen nicht über Neustarts hinweg stillschweigend verbunden; übernommene
Anfangszustände und begrenzte Rohberichtsabdeckung bleiben ausdrücklich sichtbar.

Speicherbedarf nach drei und sechs Monaten anhand der beobachteten Datenrate
neu bewerten, bei Platzwarnungen früher. Die Kapazitätsgrenzen des Hostrunners
begrenzen die Aufnahme; sie ersetzen keine ausreichend große Archivplatte.
Aktuelle Tests, Reviewumfang, Veröffentlichung und Liveprüfung werden im
[Entwicklungsstand](entwicklungsstand.md) getrennt nachgewiesen.
