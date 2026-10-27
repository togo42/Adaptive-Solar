# Lernfortschritt im Home-Assistant-Dashboard

Stand: 27.10.2026; Diagnoseattribute von Adaptive Solar 0.2.12. Die optionale
Lovelace-Karte [adaptive-solar-learning-card.js](../examples/lovelace/adaptive-solar-learning-card.js)
zeigt den vorhandenen Lernstatus. Sie liest ausschließlich die konfigurierten
Prognosedatenstatus-Entitäten: keine Dienste, Recorderabfragen, zusätzlichen
Wetterabrufe, Helper oder Änderungen an Messbindungen.

## Darstellung und Grenzen

- Die Übersicht trennt die konfigurierten Anlagen. Nicht verfügbare oder über
  15 Minuten alte Ausgabestände werden gekennzeichnet; unvollständige
  Schattenfenster-Summen bleiben fehlend.
- Je Stufe erscheinen angenommene, abgelehnte und noch nicht abgeschlossene
  Zielintervalle. Überlappende Ablehnungsgründe werden einzeln angezeigt, nicht
  zu einer vermeintlichen Gesamtfehlerquote addiert.
- NWP und GHI erhalten eigene Fortschrittsbalken für `target_days` und
  `unique_target_hours`. Die Standard-Mindesthistorie von 28 Tagen und 240 Stunden
  gilt je Regime; die regimeübergreifenden flachen Summen werden dafür nicht
  verwendet. Volle Balken ersetzen keine bestandene Holdout-/Horizontprüfung.
- Sobald vorhanden: Physik- und Residual-Validierungs-MAE in Watt als Balken und
  Zahlen, Fehlerreduktion `100 * (1 - Residual-MAE / Physik-MAE)` und Anteil
  gewonnener Prüftage. Die Fehlerreduktion ist bei Physik-MAE null nicht definiert.
  Fehlende/ungültige Zahlen bleiben `—`, echter Fehler null bleibt null.
- Validierte Lead-Bins zeigen den tatsächlich unterstützten Vorlaufbereich,
  Fehlerreduktion, Gewinntage und den empirischen Kalibrierungsradius. Das sind
  interne Prüfergebnisse, kein Nachweis von P10/P90 oder einer Überlegenheit
  gegenüber Helios/Open-Meteo.
- Das Schattenlernen zeigt freigegebene Fenster, aktuelles Azimut-/Höhenfenster,
  Viertelstundenaufnahmen und freigegebenen Direktlicht-Durchlass. Ein noch nicht
  freigegebenes Fenster ist neutral; Fensteranzahl und Faktor sind keine
  Genauigkeitsprozente. Der Sonnenstand bezieht sich auf den Ausgabestand.
- Messqualität und Ablehnungsgründe lassen sich aufklappen. Über
  „Original-Lernstatus öffnen“ ist die native Entität erreichbar.

Die Karte zeigt den aktuellen Stand und zeichnet keine Lernkurve auf. Die
umfangreichen Lernattribute sind von der regulären Recorderaufzeichnung
ausgenommen. Ein späterer Zeitverlauf benötigt eine separat definierte Erfassung;
aktuelle Werte dürfen keine früheren Lernstände vortäuschen. Fachliche Verträge:
[Bedienung](bedienung.md#5-sensoren-und-lernstatus),
[Implementierungsvertrag](implementation-contract.md),
[Validierungsplan](validierung.md).

## Optionale Einrichtung

Die JavaScript-Datei als Lovelace-Ressource vom Typ `module` registrieren. Möglich
sind eine lokale Datei unter `/config/www/` mit versionierter `/local/`-URL oder
der Inline-Modulweg der HA-Dashboard-API. Die Ressource enthält keine relativen
Imports und keine privaten Anlagenkennungen. Eine Ressource allein ergänzt noch
keinen Tab. Bereits geöffnete Browser müssen neue Ressourcen gegebenenfalls
neu laden. Die Datei ist ein optionales Repositorybeispiel und wird nicht
automatisch vom HACS-Integrationsupdate installiert.

Fiktive Konfiguration im Lovelace-Karteneditor:

```yaml
type: custom:adaptive-solar-learning-card
entity: sensor.example_forecast_quality
stage_id: example
name: Beispielanlage
```

`stage_id` ist der Schlüssel unter `attributes.learning`. Nur wenn dort exakt
eine Stufe enthalten ist, kann die Kennung entfallen. Bei mehreren Stufen wird
keine automatisch ausgewählt. Für eine gemeinsame Übersicht:

```yaml
type: custom:adaptive-solar-learning-card
mode: overview
plants:
  - entity: sensor.example_forecast_quality
    stage_id: example
    name: Beispielanlage
```

Eine vorhandene Dashboardansicht über die Lovelace-API mit frischem Konfigurationshash
gezielt ergänzen. Vorher vollständige Konfiguration und Ressourcenliste lokal
sichern; anschließend bestehende Ansichten und neue Karte vollständig zurücklesen
und auf Desktop/Mobilgerät rendern. Rückweg: die ergänzte Ansicht entfernen und die
nur dafür registrierte Ressource nach Prüfung ihrer Verbraucher löschen.

## Prüfung

```bash
node --check examples/lovelace/adaptive-solar-learning-card.js
node --test tests/frontend/test_learning_card.mjs
```

Die Frontendtests decken getrennte Regime, kalte Historie, echte Nullwerte,
Fehlerreduktion, Lead-Gates, Schattenfreigabe, fehlende Energiebinding,
überlappende Ablehnungen, veraltete/unverfügbare Quellen, mehrdeutige Stufen und
HTML-Escaping ab. Reale Darstellung bleibt eine zusätzliche Prüfung in HA.
