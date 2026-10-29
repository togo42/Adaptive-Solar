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
im [Datenvertrag der Korrekturen](../technik/forecast-repairs.md).

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

Geprüfte Implementierung `af3df57`: **1102 Tests ohne Skips**, Ruff und Dependencycheck erfolgreich. Vollständiger Grok-4.7/high-Textreview über **111 Originaldateien**, 1.500.456 Payloadbytes und 27 erfolgreiche Turns: **mergeable, keine Findings**. Separater Nachaudit bestätigt identische Original-/Promptbytes, Quell-/CLI-Hashes, native Modell-/High-Identität, erfolgreichen Abschluss und null Compaction/Tools. Receipt-SHA256 `56788cd17274a57645bbc676ded073ff07c8792625d6baf3aca949e93ce64724`.

Quell- und Testangaben stehen in den [Prüfnachweisen](../entwicklung/pruefnachweise.md);
konkrete Installationsprotokolle bleiben privat. Nachträgliche Statusangaben
liegen außerhalb des eingefrorenen Reviews.
Tests/Review beweisen keine Prognoseüberlegenheit oder qualifiziertes produktives ML.

## Veröffentlichung

Historische Quell-, Test- und Veröffentlichungsangaben stehen in den
[Prüfnachweisen](../entwicklung/pruefnachweise.md). Anlagenspezifische Installations-
und Laufzeitprotokolle werden privat geführt.
