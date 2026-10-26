# Adaptive Solar 0.2.11

## Änderungen

- Projektlizenz GPL-3.0-only mit vollständigem Lizenztext im Repository, Pythonpaket
  und HACS-Integrationsordner. Fremdlizenzen und Wetterdienstbedingungen bleiben separat.
- Öffentliche Anleitungen für Installation, Konfiguration, Sensoren, native Energy,
  Datenschutz, Fehlerbehebung und Entwicklung ergänzt. Der HAOS-Weg enthält den
  konkreten persistenten Pfad, Payloadvorbereitung und Rückweg; amd64/CPython 3.14/Musl
  bleibt die qualifizierte Binärplattform.
- Prognosehorizont als einschließlich heute klargestellt, Recherchen mit direkten
  Primärquellen konsolidiert und unbelegte Fehlerbereiche/Ranglisten entfernt.
- HACS-Mindestversion auf den ältesten geprüften Core 2026.10.2 angeglichen.
  Die unbenutzte veraltete Versionskonstante entfällt.
- Der Review-Helfer nimmt auch endungslose `LICENSE`-Dateien in seinen hashgebundenen
  Textumfang auf. Ein Regressionstest prüft zugleich den Ausschluss privater Dateien.
  Das lokale vollständige Transportbudget ist auf 1.250.000 Bytes angepasst;
  unveränderte native Prüfungen verbieten weiterhin Kontextkürzung und Teilurteile.

## Upgrade von 0.2.10

Forecast-/Lernalgorithmen, Runtimepins, Feature-/Historienvertrag und Sensor-IDs bleiben
unverändert. Ein bestehender passender scikit-learn-Musl-Payload wird weiterverwendet;
für dieses Update ist kein erneuter Binärbau vorgesehen. Bestehende Anlagenparameter,
Messbindungen und Energy-Einstellungen benötigen keine Änderung. Nach Download
über HACS ist ein Core-Neustart erforderlich, damit die neue Version geladen ist.

Ein neuer Tag wird veröffentlicht; der bestehende Tag 0.2.10 wird nicht überschrieben.
Vorherige ursprüngliche Forschungsfassungen bleiben über die Git-Historie zugänglich.

## Prüfstand

Je 894 Quelltests ohne Fehler oder Skips unter Core 2026.10.3/.4 bestanden;
Ruff und Dependencycheck erfolgreich. Das 0.2.11-Wheel enthält alle 23
Integrationsdateien bytegleich und korrekte GPL-Metadaten.

Diese Releasebeschreibung ist Teil des zur Prüfung vorgesehenen Quellstands.
Tests, neuer vollständiger Grok-4.7/high-Review, Veröffentlichung und HA-Rücklese
werden nach Abschluss mit ihrer jeweiligen Bindung im [Entwicklungsstand](entwicklungsstand.md)
und den [Reviewnachweisen](review-findings.md) dokumentiert. Frühere Receipts gelten
nicht automatisch für diese Version oder die geänderten Forschungsdateien.
Qualifiziertes produktives Lernen und ein fairer prospektiver Genauigkeitsvorsprung
gegen beide Referenzen bleiben eigenständige offene Nachweise.
