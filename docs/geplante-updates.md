# Geplante Änderungen für das nächste Update

Stand: 26.10.2026. Diese Liste dokumentiert beauftragte Folgeänderungen und deren Umsetzungsstand.

## AS-UI-001: Doppelte Gesamtanzeige bei einer Ausgangsstufe vermeiden

**Status:** in Version 0.2.10 implementiert und mit nativen HA-Regressionstests geprüft. Anwenderwunsch vom 25.10.2026. Produktive Installation wird separat im Entwicklungsstand dokumentiert.

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

### Umsetzung in 0.2.10

Neue Einträge mit einer Ausgangsstufe erzeugen nur deren zehn Sensoren und ein Gerät. Beim Upgrade bleiben bereits vorhandene Gesamt-Sensoren unter unveränderten Entity-/Unique-IDs verfügbar; sie werden als Kompatibilitätsanzeigen vom Standard ausgeblendet und dem bestehenden Einzelgerät zugeordnet. Benutzerdefinierte Namen, Deaktivierungen und ausdrücklich gesetzte Ausblendungen bleiben erhalten. Das dann leere, ausschließlich zu diesem Eintrag gehörende Gesamtgerät entfällt. Mehrere Ausgangsstufen zeigen weiterhin ihre Einzelgeräte und das Gesamtgerät. Alte Gesamtanzeigen werden bei einem solchen Wechsel wieder eingeblendet; ausdrücklich vom Benutzer ausgeblendete Anzeigen bleiben ausgeblendet.

Wird eine Ausgangsstufe im Optionsdialog ausdrücklich entfernt, entfernt die Integration deren eigene Sensorregistrierungen und leere Geräte. Die Recorder-Historie wird nicht gelöscht. Geräte mit fremden Entitäten oder Zuordnungen werden nicht entfernt. Die Migration bearbeitet nur bekannte eigene Sensorarten; Berechnung, Energy-Anbindung und Historienfingerprints bleiben unverändert. Vor einem produktiven Upgrade werden Verbraucher der entfallenden redundanten Geräte-IDs geprüft; Sensorverweise müssen nicht umgeschrieben werden.

Regressionen: neue AC-/DC-Einträge, mehrere Strings an einer Stufe, Upgrade mit Benutzeranpassungen, identische Energie-/Messhistorie nach erneutem Laden sowie wiederholter Wechsel zwischen einer und mehreren Stufen. Siehe [Versionsinformationen](release-0.2.10.md).
