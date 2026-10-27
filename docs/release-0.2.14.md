# Adaptive Solar 0.2.14

## Änderungen

- Eng begrenzte Normalisierung kleiner negativer Nachtstrahlung mit expliziten
  Rohwertdiagnosen; keine Nullfüllung fehlender Wetterwerte und keine Änderung
  von Tageslichtwerten oder allgemeinen Abdeckungsanforderungen.
- Ausgegebene historische Tagesstartprognosen bleiben mit ursprünglicher
  Konfigurationsprovenienz erhalten, auch wenn inkompatible Lernhistorie nach
  physischer Neukonfiguration verworfen werden muss.
- Administratoraktion zum gezielten Import eines bereits verlorenen Original-
  Tagesstartwerts einschließlich ursprünglicher Konfiguration. Kein Lernimport,
  keine Rekonstruktion aus aktuellem Wetter und kein Überschreiben vorhandener Tage.

Die genauen Grenzen, Diagnosen, Provenienz und der Wiederherstellungsablauf stehen
im [Datenvertrag der Korrekturen](forecast-repairs.md).

## Upgrade und Rückweg

Von 0.2.13 bleiben Optionen, Entity-/Unique-IDs, Geräte, Messbindungen und Energy-
Einstellungen unverändert. Runtimepins: pvlib 0.16.1, scikit-learn 1.9.1;
Lernfeaturevertrag `beam-shade-table-v1`. Kein Core-/OS-Upgrade. Nach HACS-Download
einmal Core neu starten. Kompatible bestehende Historie bleibt erhalten.

Vor Download aktuelle Komponentenbytes und Historienstores sichern. Rückweg:
0.2.13 erneut installieren; gesicherte Stores nur bei tatsächlich nötiger
Rückkehr und entladener Integration verwenden. Die alte Version kennt die neue
Provenienz nicht; nach zwischenzeitlicher physischer Änderung darf sie historische
Werte daher nicht als Beleg für den neuen Konfigurationsstand übernehmen.

## Prüfstand

Lokale Implementierung; Tests, gebundener Grok-4.7/high-Review, Veröffentlichung,
abgeschlossene Remote-CI und produktive HA-Übernahme werden vor Abschluss separat
nachgewiesen. [Aktueller Stand](entwicklungsstand.md). Keine Aussage über
Prognoseüberlegenheit, qualifiziertes produktives ML oder allgemeine Wettergüte.
