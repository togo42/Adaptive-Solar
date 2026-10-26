# Adaptive Solar 0.2.10

## Änderungen

- Morgen-/Abenddämpfung je String im Einrichtungs- und Optionsdialog, unabhängig von Hersteller und AC-/DC-Ausgangstyp. Faktor 0 deaktiviert die Korrektur; 1 entspricht voller Randdämpfung bei Sonnenauf-/untergang. Der Verlauf ist bis zur Tageslichtmitte linear. Die Anwendung erfolgt nach der Temperaturrechnung und vor der gemeinsamen Ausgangsgrenze. Horizontpunkte bleiben je String getrennt konfigurierbar.
- Umsetzung von [AS-UI-001](geplante-updates.md): eine Ausgangsstufe erzeugt standardmäßig ein Gerät ohne zusätzliche Gesamtanzeige. Bestehende Gesamt-Sensoren bleiben als ausgeblendete Kompatibilitätsanzeigen unter ihren IDs erhalten. Mehrere Ausgangsstufen behalten Gesamt- und Einzelanzeigen. Benutzeranpassungen bleiben erhalten.
- Installation und künftige Aktualisierung aus dem öffentlichen [GitHub-Repository](https://github.com/togo42/Adaptive-Solar) über HACS. Manifest und mitgeliefertes Markenbild enthalten die dafür erforderlichen Projektangaben.
- Wiederhergestellte Sensorwerte steuern keinen Nowcast, keine Umwelteinblendung und keine neuen Energieanker. Reguläre neue Berichte werden weiter verwendet. Die Lernqualitätsdiagnose nennt getrennte Gründe für verspätete Ausgaben, kurze Zielzellen und bei Ausgabe bereits angeschnittene Quellzellen.

## Hinweise zum Upgrade

Unveränderte Null-Dämpfungswerte bewahren alte Konfigurationen und Fingerprints. Neue aktive Dämpfungen oder ein geändertes Horizontprofil ändern die Prognosekonfiguration; alte Lernhistorie wird gemäß bestehendem Persistenzvertrag nicht ungeprüft weiterverwendet. Die Anzeige-Migration selbst ändert weder Messhistorie noch Forecastwerte oder die native Energy-Anbindung.

Das vorhandene Horizontmodell wirkt auf direkte Strahlung. Es bildet weder das gesamte Open-Meteo-Teilverschattungsmodell noch elektrische Bypassverluste nach. Übernommene Profile und Dämpfungen sind Konfigurationsannahmen; eine Annäherung an eine andere Prognose beweist keine bessere Genauigkeit.

Der aktualisierte Featurevertrag setzt alte Archivfeatures und daraus abgeleitete Lernmodelle zurück, da deren restaurierte Eingaben rückwirkend nicht qualifiziert werden können. Unabhängig geprüfte Messintervalle und bereits ausgegebene Tagesbeginn-Prognosen bleiben unter unveränderter physischer Zuordnung erhalten. Das ist von der Anzeige-Migration und dem möglichen zusätzlichen Reset bei einer geänderten Horizont-/Dämpfungskonfiguration zu unterscheiden.

## Validierung und Installation

Je 880 Tests ohne Fehler oder Skips mit HA Core 2026.10.2/.3/.4 bestanden; drei reguläre Wheel-Installationen mit isolierter Paketprüfung und erfolgreichem `pip check`. Die alten Prüfumgebungen blieben erhalten. Der gebundene externe Review wird vor der Veröffentlichung abgeschlossen. Produktive Installation und Rückleseprüfung werden nach Abschluss im [Entwicklungsstand](entwicklungsstand.md) dokumentiert. Der reale Genauigkeitsnachweis bleibt separat offen.
