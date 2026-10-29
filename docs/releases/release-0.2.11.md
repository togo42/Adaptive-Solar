# Adaptive Solar 0.2.11

## Änderungen

- Projektlizenz GPL-3.0-only mit vollständigem Lizenztext im Repository, Pythonpaket
  und HACS-Integrationsordner. Fremdlizenzen und Wetterdienstbedingungen bleiben separat.
  Der Paket-Einstieg trägt zusätzlich einen eindeutigen SPDX-/Copyright-Hinweis.
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
  Ein größerer Kontext wird ausschließlich für den Review-Kindprozess angefragt;
  ein kompaktierter erster Versuch wurde verworfen, nicht als Review gewertet.

- Wiederhergestellte Abregelungssignale gelten als unbekannt, auch bei `off`.
  Energie-Lernen und Power-Nowcast bleiben gesperrt. Nach einem echten `off` muss
  der Leistungsbericht neuer als die Freigabe sein; der erste neue Zählerbericht
  ankert nur, der nächste liefert wieder ein Intervall. AC/DC und Wiederanlauf
  werden mit echten HA-Ereignissen getestet.

## Upgrade von 0.2.10

Runtimepins, physikalische Messgrenzen, Featurevertrag und Sensor-IDs bleiben
unverändert. Die Eingangsprüfung der Abregelung wird wie oben beschrieben korrigiert. Ein bestehender passender scikit-learn-Musl-Payload wird weiterverwendet;
für dieses Update ist kein erneuter Binärbau vorgesehen. Bestehende Anlagenparameter,
Messbindungen und Energy-Einstellungen benötigen keine Änderung. Nach Download
über HACS ist ein Core-Neustart erforderlich, damit die neue Version geladen ist.

Vorhandene Messintervalle, Archivfeatures und Tagesanfangsprognosen werden innerhalb
der bisherigen Provenienz-/Aufbewahrungsgrenzen weiterverwendet. Alte Intervalle
belegen technisch nicht, ob das damalige Abregelungssignal wiederhergestellt war.
Eine Betreiberbestätigung fehlender Abregelung ist kein nachträglicher technischer
Signalnachweis. Betreiber müssen ihre Althistorie vor weiterer Lernnutzung entsprechend
qualifizieren; bei Unsicherheit Eintrag deaktiviert lassen und einen gezielten
Historienneustart klären. Keine direkte Bearbeitung von `.storage` empfohlen.

Neue kontrollierte Messintervalle tragen `curtailment_measurement_contract=non-restored-control-v1`.
Alte Zeilen erhalten dieses Merkmal nicht nachträglich; Qualitätsdiagnosen zählen
sie als `legacy_curtailment_intervals` mit Scope
`retained_history_requires_operator_qualification`. Das Merkmal beschreibt nur die
HA-Eingangsprüfung und zertifiziert keine physikalische Quelle.

Für diese Version wurde ein neuer Tag veröffentlicht; der bestehende Tag 0.2.10 bleibt unverändert.
Vorherige ursprüngliche Forschungsfassungen bleiben über die Git-Historie zugänglich.

## Prüfstand

Je **900 Quelltests ohne Fehler oder Skips** unter Core **2026.10.2/.3/.4** bestanden;
Ruff und Dependencychecks erfolgreich. Das nach der Korrektur neu gebaute Wheel
wurde separat regulär installiert und gegen alle 23 Integrationsdateien sowie
GPL-Metadaten geprüft; sieben native Core-.4-Modulimporte erfolgreich.

Die Implementierung aus Commit `9070886` erhielt einen vollständigen
Grok-4.7/high-Review aller 96 öffentlichen Textdateien: keine Findings und keine
Kontextkürzung. Hauptbranch- und Tag-CI vor der nativen HACS-Installation erfolgreich.
Öffentliche Quell- und Testangaben stehen in den [Prüfnachweisen](../entwicklung/pruefnachweise.md).
Anlagenspezifische Installationsprotokolle werden privat geführt. Qualifiziertes
produktives Lernen und der prospektive Genauigkeitsvergleich bleiben separate Nachweise.
