# Adaptive Solar 0.2.20 – unveröffentlichter Releasekandidat

Stand: 30.10.2026. **Vorbereitet, noch nicht veröffentlicht oder installiert.**
Der veröffentlichte Release bleibt [0.2.19](release-0.2.19.md). Manifest und
Paketmetadaten tragen bereits die Kandidatenversion 0.2.20. Abschließender
Codex-Review, Releasebuild und CI dieses Kandidaten stehen noch aus;
diese Hinweise sind keine Freigabe zur produktiven Aktivierung.

## Änderungen gegenüber 0.2.19

### Trainingsabdeckung ausschließlich offline untersuchen

Der separate `SupportGuardLearner` prüft, ob eine Merkmalslage durch den
tatsächlichen Trainingsblock gestützt ist. Er verbindet dauergewichtete
Merkmalsgrenzen, gemeinsame Prototypabstände und kreisförmige Azimut-/Saisonwerte.
Validierungs- und Kalibrierungsdaten passen diese Grenzen nicht an. Bei fehlender
Stützung verwendet der Kandidat die begrenzte Physikbaseline mit eigener Diagnose.

`scripts/analyze_learning_support.py` vergleicht Physikbaseline, bisherigen Lerner
und Guard auf denselben eingefrorenen Aufgaben vor dem Leistungsnowcast.
Echte Archivempfangszeiten, Quellen- und Konfigurationsidentität, qualifizierte
Istwerte sowie ein deklarierter Prüfplan bleiben erforderlich. Auch vollständig
fehlende jüngere Ausgabeversuche bleiben sichtbar und verhindern einen
stillschweigenden Rückgriff auf ältere Kurven. Ohne vorab deklarierten Plan ist
die Auswertung nachträglich und diagnostisch.

Die HA-Integration verwendet weiterhin **`ResidualLearner`**. Der Guard erhält
keine HA-Option, keinen Dienst und keine automatische Aktivierung. Seine Policy
ist nicht an realer Prognosegüte validiert; sie erkennt keine veränderte
Ertragsbeziehung bei unveränderten Eingaben. Vertrag und Grenzen stehen unter
[Trainingsabdeckung offline prüfen](../technik/learning-support-guard.md).

### Istwertqualität optiert an Originalquellen binden

`scripts/qualify_actuals.py` erzeugt aus vollständigen Originalintervallen und
expliziten Quellenattestierungen eine separate Qualitätsrevision für
Recorder-Stundenenergie. `scripts/continuous_quality.py` ergänzt den lokalen
Probelauf und die begrenzte fortlaufende Ableitung. `--quality-bindings` beim
Beobachtungscollector beziehungsweise `quality_bindings` beim Archivhost sind
ausdrücklich optiert und schließen die bisherige statische `quality`-Maske aus.

Neue exportierte `qualified_interval`-Originale tragen `source_binding` mit
Energie-Entity, Konfigurationshash und Producerquellhash. Der v2-Vertrag verlangt
passende Pins an jedem vollständigen verwendeten Delta, eindeutige 1:1-Zuordnung,
lückenlose UTC-Stunden und getrennt belegte Konfigurations-, Mess- und
Abregelungsfacetten. Widersprüche bleiben sperrend; fehlende Daten werden nicht
zu Nullwerten oder Freigaben. Neue Qualitätsrevisionen erhalten ihren tatsächlichen
Abschlusszeitpunkt als `validated_at`; Originalempfang und Rohdaten bleiben erhalten.

**Alte Originale aus 0.2.18/0.2.19 erhalten keine Pins nachträglich.** Eine neue
v2-Policy qualifiziert sie deshalb nicht. Eine ausdrücklich belegte historische
v1-Prüfung bleibt ein eigener Vorgang. Hashgleichheit belegt allein keine
physische Messgüte. Format, Grenzen und Probelauf stehen im
[Istwert-Qualitätsadapter](../archiv/istwert-qualitaetsadapter.md).

### Aufnahme, Zeitbezüge und Vergleichsarme korrigieren

- Der HA-Producer friert Rohberichte für `state_changed` an `last_updated` ein;
  `state_reported` behält seine Ereigniszeit. Der bestehende gesonderte Zeitpfad
  der Energiemessung bleibt erhalten. Die Korrektur verändert neue Exporte,
  keine historischen Originale.
- Referenzstunden werden nach Normalisierung auf UTC auf das Stundenraster und
  doppelte absolute Zeitpunkte geprüft. Fehlerhafte Open-Meteo-Objekte werden
  als `WeatherError` behandelt und im bestehenden Fehlerpfad archiviert.
- Der reine NWP-Physikarm wird unabhängig von optionalen lokalen Korrekturen
  gebildet. Ein Ausfall der operativen Kohorte entfernt dadurch nicht mehr
  einen ansonsten vorhandenen NWP-Vergleichspunkt. Fehlende Mitglieder bleiben
  fehlend. Integrierte Azimutmerkmale verwenden eine kreisförmige Mittelung.
- Capture-, Replay-, Forecast- und Auswertungshelfer schützen Eingaben,
  Programm-/Ressourcendateien und deren Link-Aliase vor Ausgabeüberschreibungen.
  JSONL-Aufnahmen prüfen das geöffnete Ziel unter Sperre; Archive und
  Originalreceipts bleiben getrennt von abgeleiteten Berichten.
- Hoststatus und Datasetexport weisen auch interne Archivziele sowie die
  geprüften Pfadaliase zurück; Statusberichte dürfen keine Hostkonfiguration
  ersetzen. Der Ensemble-Replay bindet Wetterprodukte an die ursprünglichen
  Anfragekoordinaten des gewählten Standorts.

## Getrennte Installation und Rückwege vorbereiten

Diese Schritte beschreiben einen späteren freigegebenen Upgradepfad. In der
Releasevorbereitung werden weder HA noch externe Hosts geändert.

### Home Assistant

Vor einem späteren Update abgeschlossene HA-Sicherung und bisherigen vollständigen
Komponentenstand erhalten. Nach Veröffentlichung die neue Version über HACS
herunterladen und einmal Core neu starten. Bestehende Einträge, Entity-IDs,
Optionen und passende Historien weiterverwenden; kein Core-/OS-Upgrade oder neuer
Binärabhängigkeitsbau ist vorgesehen. Abhängigkeitspins, Featurevertrag und
bisherige Lerngates ändern sich nicht; die Azimutmittelung wird wie oben beschrieben
korrigiert. Es gibt keine Reinitialisierung und keine direkten `.storage`-Änderungen.

Anschließend Eintragsstatus, Prognosen, Entity-IDs, Optionen, Historien,
Tagesbeginnwerte, Konfigurationsprüfung und Repairs prüfen. Nur beim bewusst
aktivierten Originalexport neue Intervalle und deren tatsächliche Quellenpins
zurücklesen. Producerprovenienz wird für die Coordinatorlaufzeit gehalten;
ein Dateiaustausch unter laufendem Coordinator genügt nicht.

Für den Code-Rückweg den gesicherten vollständigen Komponentenstand oder den
veröffentlichten Release 0.2.19 verwenden und Core neu starten. Vorhandene
Historien erhalten; eine Sicherung ersetzt keinen geprüften Wiederherstellungsweg.
Neue gepinnte Originale bleiben unverändert archiviert. Ein älterer Producer
liefert anschließend keine für v2 ausreichenden Pins mehr; seine Stunden werden
nicht durch Übernahme der neuen Policy qualifiziert.

### Optionaler externer Archivhost

HACS aktualisiert weder Hosthelfer, deren Laufzeit und Konfiguration noch Timer
oder Dashboardressourcen. Den Hoststand separat nach
[Hostinstallation](../archiv/archiv-host-installation.md) einfrieren und testen.
Bestehende Konfiguration und vorherigen Releasepfad für den Rückweg erhalten.
Ein realer v2-Probelauf benötigt zuerst neue Originalintervalle des passenden
HA-Producers, einen erhaltenen Konfigurationsanker und eine begrenzte Policy
mit drei gesondert geprüften Facetten. Policies übernehmen neue Producerpins
oder Gültigkeitszeiträume nicht automatisch.

Zuerst lokal mit eingefrorener Archivkopie prüfen. Ein später gesondert
autorisierter Host-Probelauf muss Writerlock, Archivvolumen, Auswahlbudgets,
Ankerretention, Rohdatenhashes, Qualitätszeit und Fehlermeldungen kontrollieren,
bevor über eine reguläre Taktung entschieden wird. Rücknahme bedeutet vorherigen
Hostrelease und Konfiguration wiederherstellen; Originale und neue
Qualitätsrevisionen bleiben als Evidenz erhalten. Negative Masken verlangen
fachliche Klärung und werden nicht zur Ergebnisverbesserung gelöscht.

## Offene Prüfung und Aussagegrenzen

Die historischen [Prüfnachweise](../entwicklung/pruefnachweise.md) gelten für
ihre jeweils gebundenen Quellen. Der abschließende Codex-Review für diesen
zusammengeführten Kandidaten sowie dessen vollständige Tests, Build- und
CI-Nachweise sind noch offen. Frühere Abnahmen werden nicht auf neue Bytes
übertragen. Veröffentlichung, produktive Installation und reale Quellen-/Lernabnahme
sind weitere getrennte Schritte.

Ein synthetischer Probelauf zeigt nur die Verkabelung. Weder ein Review noch
Tests, Hashpins oder Qualitätsableitung belegen physische Quellenvalidität,
produktive Lernfreigabe oder bessere Prognosen als andere Integrationen.
Dafür bleiben passende prospektive Originale, qualifizierte Messwerte und
vollständige gepaarte Tage nach dem [Validierungsplan](../entwicklung/validierung.md)
erforderlich. Der Offline-Guard bleibt auch nach einem späteren Release offline.
