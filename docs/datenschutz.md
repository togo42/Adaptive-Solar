# Datenschutz und Datenflüsse von Adaptive Solar

Stand: 27.10.2026; beschrieben ist das Referenzrelease 0.2.14 mit lokalem Implementierungsnachtrag, keine
Datenschutzbewertung aller anderen Integrationen der jeweiligen HA-Installation.

## 1. Externe Verbindungen

| Vorgang | Ziel und übertragene Daten |
| --- | --- |
| Wetterabruf | HTTPS `api.open-meteo.com/v1/forecast`: Breitengrad, Längengrad, Modellkennung, Wettervariablen, Horizont, Einheiten und UTC-Zeitformat; außerdem netzbedingt die öffentliche Quell-IP |
| HACS-Installation/Update | GitHub über HACS; unterliegt dessen eigener Implementierung und Bedingungen |
| Optionale lokale CLI `forecast.py --live` | Derselbe Wetterabruf für die explizit ausgewählte Standortdatei |
| Separat gestarteter externer Review | Nur der ausdrücklich vorbereitete öffentliche Quelltextumfang geht an den Reviewer; kein Bestandteil des normalen HA-Betriebs |

Die Integration berechnet Physik und Residualmodelle lokal. Ihr Wetterrequest enthält
keine Entity-IDs, Zählerstände, Leistungsreihen, Lernzeilen, Batteriesignale oder
HA-Zugangstokens. Im Integrationscode ist kein Telemetrie-/Crashreportingdienst
implementiert. Andere HA-Integrationen oder Apps können eigene Verbindungen herstellen.

Der Coordinator aktualisiert regulär alle fünf Minuten; je Modell/Anlageneintrag
gibt es einen Wettercache von einer Stunde. Das ist keine globale Abrufquote:
Fehlerwiederholungen, Reloads, mehrere Einträge und eigene Live-CLI-Aufrufe können
weitere Requests erzeugen. Die kostenlose API erlaubt laut den am 26.10.2026
geprüften [Bedingungen](https://open-meteo.com/en/terms) nichtkommerzielle Nutzung
mit Grenzen unter 10.000 Aufrufen/Tag, 5.000/Stunde und 600/Minute. Mengen können
nach Abfrageumfang gewichtet werden; aktuelle Bedingungen beim Provider prüfen.
Open-Meteo nennt dort technische IP-Verarbeitung und mögliche Koordinaten in
Webserverlogs mit Löschung nach 90 Tagen. Wetterdaten unterliegen CC BY 4.0;
bei einer eigenen Weiterveröffentlichung die [Attribution](https://open-meteo.com/en/licence)
beachten. Die GPL des Projektcodes ersetzt diese Bedingungen nicht.

Der lokale Nachtrag kann nach Abruffehlern vorhandenes Wetter mit unverändertem
ursprünglichem Empfang höchstens zwölf Stunden lang weiterverwenden. Dadurch
entsteht keine zusätzliche externe Datenübertragung; fehlgeschlagene Abrufe
können weiter wiederholt werden. [Cache- und Fehlerdiagnosen](forecast-resilience.md).

## 2. Lokale Daten

Standort, Geometrie, numerische Modellparameter und optionale Entitybindungen
liegen im nativen HA-Konfigurationseintrag beziehungsweise dessen Optionen.
Laufzeitdaten umfassen archivierte Forecastfeatures, später gemessene Energieintervalle,
Lern-/Qualitätsdiagnosen, ausgegebene Tagesbeginn-Snapshots und die gelernte
Direktstrahl-Schattentabelle. In den Historienstores
werden keine ausführbaren Modell-Pickles gespeichert; Modelle entstehen lokal aus Zeilen.

Je Eintrag gibt es einen aktuellen Store `adaptive_solar.<entry_id>.history_v2` und
einen nur lesend berücksichtigten Legacy-Key. Forecast- und Istintervalle sind auf
höchstens 120 Tage, 60.000 Forecastzeilen und 30.000 Istzeilen begrenzt;
Zeilengrenzen können den Zeitraum verkürzen. Tagesbeginn-Snapshots werden separat
ab sieben lokalen Tagen vor dem aktuellen Tag aufbewahrt. Seit 0.2.14 haben sie
eigene ursprüngliche Konfigurationshashes, einen Anlagenidentitätshash, Zeitzone,
Stufenkennungen und ursprüngliche Leistungsgrenzen. Die Administratoraktion zum
Originalimport verarbeitet eine private Originalkonfiguration nur lokal und
persistiert davon diese Metadaten, nicht das vollständige Originalobjekt.
HA-Aktionsspuren/Recorder/Logs können eigene Datenkopien enthalten.
[Provenienz und Import](forecast-repairs.md).

Die Tabelle `beam_shade_v1` speichert je Stufe und Sonnenstandsfenster bis zu
24 zeitlich qualifizierte UTC-Viertelstunden mit echtem Mess-/Verfügbarkeitszeitpunkt
und Transmissionsfaktor. Im lokalen Nachtrag enthält Schema 3 außerdem höchstens
64 Freigabeänderungen je Fenster. Alte Schema-1/2-Proben bleiben separat als
unqualifizierte Altdaten diagnostisch erhalten, ebenfalls höchstens 24 je Fenster;
sie begründen keine aktive Freigabe. Gespeicherte
Zeilen können länger bestehen bleiben, aber die Anwendung qualifiziert nur Belege
innerhalb 45 Tagen sowie ausreichende Tageszahl und begrenzte Streuung. Die Tabelle
zählt nicht gegen die genannten Forecast-/Istzeilengrenzen. Physische Änderungen oder geänderte relevante
Sensor-/Wettermodellbindungen setzen sie zurück; ein reiner Wechsel der
Prognosetage erhält sie. Es gibt keine externe Synchronisierung.
[Persistenzvertrag](implementation-contract.md).

Der optionale Leistungs-Nowcast-Verlauf ist flüchtig und auf 128 Originalberichte
pro Stufe begrenzt; er wird nicht als eigener Store persistiert. Auch der
[frühe Bias-Shadow](early-bias-shadow.md) speichert keine ausführbaren Modelle.
Seine Diagnosen und getrennten Kandidatenpunkte dienen der lokalen Beobachtung.
Das [Modellvergleichsarchiv](model-comparison-archive.md) liegt im separaten festen
Store `adaptive_solar.<entry_id>.comparison_v1`, unabhängig vom Primary-Messstore. Es umfasst Wettermitglieder,
operative Ausgabe/Baseline und freigegebene Bias-Shadowpunkte, mit höchstens 120 Tagen,
250.000 Punktzeilen und 1024 ganzen Snapshots insgesamt; die Grenzen können den
Zeitraum verkürzen. Die erste echte lokale Receipt je Arm und lokalem Tag ab 18 Uhr
wird behalten. Große Vergleichsdaten werden nur nach echten Captures/Retentionänderungen
oder für einen noch nicht bestätigten Schreibretry gespeichert; Zählermeldungen
schreiben sie nicht mit.
Es wird keinem externen Dienst zur Verfügung gestellt. Diagnosen enthalten nur
Umfang, Arme, Zeiten und Status; vollständige private Exporte können selbst
gewählte Stufenkennungen und Forecastfeatures enthalten und gehören unter `data/`.

Recorder, HA-Protokolle und Sicherungen haben eigene Aufbewahrungsregeln, die durch
diese Limits nicht geändert werden. Auch unaufgezeichnete große Forecastattribute
schließen eine Aufzeichnung anderer Zustände/Attribute nicht aus.

## 3. Diagnose, Exporte und öffentliche Fehlerberichte

Die integrierte Diagnoseausgabe lässt Standortkoordinaten, konfigurierte Entity-IDs
und rohe Historienzeilen weg. Sie enthält unter anderem Wettermodelle, Fehlertypen,
Zeitpunkte, Zähler, begrenzte Wetterkorrektur-Rohwertbeispiele, Ressourcen-/Fitdiagnosen
und Bias-Shadow-/Lernstatus je selbst gewählter Stufenkennung. Solche Kennungen
können persönliche Bezeichnungen enthalten; die Datei vor Weitergabe prüfen.

Sensorattribute enthalten Forecastkurven, Eingangsqualität und Lerninformationen.
Screenshots und kopierte Entwicklertools-Ausgaben können zusätzliche Namen/IDs zeigen.
Die Capturewerkzeuge sind bewusste lokale Exporte mit weitergehenden Roh-/Zuordnungs-
und Zeitinformationen. `HA_URL` und `HA_TOKEN` nur lokal über die Umgebung setzen;
Archive/Zuordnungen bleiben unter ignoriertem `data/`. Generierte Prüfarbelege gehören
nach `artifacts/`, rohe Reviewdaten nach `reviews/private/`.

Vor einem öffentlichen Issue nur die zur Reproduktion nötigen bereinigten Ausschnitte
teilen. Keine Tokens, internen URLs, Standorte, kompletten Config-Entries, ungeprüften
Diagnosearchive oder Sicherungen hochladen. Eine `.gitignore` schützt keine bereits
versionierten Dateien und anonymisiert keinen exportierten Inhalt.

## 4. Entfernen und Aufbewahrung

Deaktivierung beendet nach dem Entladen die laufenden Beobachtungen und Wetterabrufe
dieses Eintrags. Der Entladepfad kann zuvor noch seinen Verlauf speichern.
Der Code hat keinen eigenen `async_remove_entry`-Bereinigungshandler für Lernstores.
Eintragsentfernung und HACS-Deinstallation sind deshalb keine Zusage, dass alle
Lern-/Recorder-/Sicherungsdaten gelöscht werden.

Für vollständige Löschung zuerst Verbraucher und Sicherungsbedarf klären, dann den
Eintrag entfernen und seine drei exakten Storekeys (Primary, Vergleichsarchiv und
nur lesender Legacy-Key) sowie Recorder-/Backupkopien
in einen getrennten administrativen Löschplan aufnehmen. Keine pauschale Löschung
von `.storage` und keine direkten Änderungen laufender HA-internen Daten als
Installationsanleitung verwenden. Es gibt derzeit keine eigene Schaltfläche für
garantiert vollständige Datenlöschung. Aufbewahrung externer Provider liegt außerhalb
der lokalen Integration.
