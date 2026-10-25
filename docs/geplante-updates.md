# Geplante Änderungen für das nächste Update

Stand: 25.10.2026. Diese Liste dokumentiert beauftragte Folgeänderungen; sie beschreibt keine bereits umgesetzten Funktionen.

## AS-UI-001: Doppelte Gesamtanzeige bei einer Ausgangsstufe vermeiden

**Status:** offen, für die nächste Version vorgesehen. Anwenderwunsch vom 25.10.2026; Umsetzung und Migration stehen noch aus.

### Problem

Die Sensorplattform erzeugt derzeit für jeden Anlageneintrag einen Gesamtbereich sowie einen Bereich je Wechselrichter beziehungsweise Laderegler. Auch bei nur einer Ausgangsstufe entstehen dadurch zwei Geräte mit inhaltlich gleichen Prognosen. Ursache: `scopes = [None, ...]` in [sensor.py](../custom_components/adaptive_solar/sensor.py).

### Gewünschtes Verhalten

- Bei genau einer Ausgangsstufe standardmäßig nur einen Gerätebereich anzeigen; keinen zusätzlichen redundanten Bereich „Gesamt“.
- Bei mehreren Ausgangsstufen die Einzelbereiche und einen zusätzlichen Gesamtbereich beibehalten.
- Entscheidend ist die Anzahl der Ausgangsstufen, nicht die Anzahl der Strings oder Solarflächen. Mehrere Strings an einem gemeinsamen Wechselrichter bleiben eine Ausgangsstufe.
- „Gesamt“ summiert ausschließlich die Ausgangsstufen desselben Anlageneintrags. Die Berechnung und ihre AC-/DC-Messgrenzen bleiben unverändert; es entsteht keine neue anlagenübergreifende Summe.
- Die Regel gilt unabhängig von Hersteller, Modell und AC-/DC-Ausgangstyp.

### Bestandsanlagen und Migration

Bestehende Entity-IDs, Unique-IDs, Historien und Verweise aus Dashboards oder Automationen berücksichtigen. Vorhandene Gesamt-Entitäten nicht ungeprüft löschen, deaktivieren oder unter neuen IDs anlegen. Die Migration muss die übersichtliche Standardanzeige herstellen und bestehende Verweise erhalten; dazu vor der Umsetzung die Geräte-/Entitätszuordnung und ihre Verbraucher prüfen. Ein erneutes Einrichten der Anlage soll nicht erforderlich sein.

### Abnahmekriterien für die Umsetzung

- Eine AC- oder DC-Ausgangsstufe erscheint ohne redundantes Gesamtgerät, auch mit mehreren angeschlossenen Strings.
- Mehrere Ausgangsstufen behalten ihre Einzelprognosen und eine korrekte Gesamtsumme; unvollständige Abdeckung bleibt als fehlend erkennbar.
- Upgrade, wiederholtes Neuladen und Wechsel zwischen einer und mehreren Ausgangsstufen erzeugen keine verwaisten oder zusätzlich duplizierten Geräte/Entitäten; bestehende Verweise funktionieren weiter.
- Native Energy-Anbindung, Prognosewerte und Lernhistorie werden durch die Darstellungsänderung nicht unbeabsichtigt verändert. AC-/DC-Grenzen und die Einschränkungen gemischter Einträge bleiben erhalten.
- Die Umsetzung erhält passende HA-Regressionstests und einen Hinweis in den Versionsinformationen.

Diese Dokumentationsänderung allein ändert weder die Integration noch produktive HA-Einstellungen.
