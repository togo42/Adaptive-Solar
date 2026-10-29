# Nachtstrahlung und historische Tagesstartprognosen

Stand: 27.10.2026, Implementierung 0.2.14. Die Regeln beheben zwei getrennte
Ausfälle; sie belegen keine höhere Prognosegenauigkeit.

## 1. Kleine negative Nachtstrahlung

Open-Meteo-Strahlung am Zeitstempel `t` beschreibt die vorhergehende Stunde
`[t−1h,t)`. Policy `small-negative-dark-hour-v1` normalisiert ausschließlich
vorhandene endliche Zahlen, wenn **alle drei** Werte GHI, DNI und DHI in
`[-1,0] W/m²` liegen und mindestens einer negativ ist. Zusätzlich muss die
pvlib-SPA-Sonnenhöhe am Anlagenstandort an allen 13 Fünfminutenstützen einschließlich
beider Intervallgrenzen höchstens −6° sein. Die drei Strahlungswerte werden dann
zu 0. Das ist eine begrenzte numerische Nachtkorrektur, keine Lückeninterpolation.

Ohne Standort, bei Dämmerung/Tageslicht, einem positiven Strahlungsanteil,
größeren negativen Werten, `null`, NaN/Inf oder Bool bleibt die Stunde fehlend.
Temperatur, Wind, Bewölkung und benachbarte Zeitstützen müssen weiterhin gültig
sein. Ohne vollständige Tagesabdeckung bleibt die Tagesenergie unverfügbar.
Parser/Sonnenstandsberechnung laufen beim HA-Wetterabruf außerhalb des Eventloops.

`weather_diagnostics.<Modell>` am Prognosestatus und in der Integrationsdiagnose
nennt Policy, Empfangszeit, `normalized_count`, bis zu acht Originalwertbeispiele
mit Start/Ende und `rejected_radiation_count` mit bis zu acht Endzeiten. Diese
Angaben gehören zur letzten erfolgreich geparsten Wetterantwort; Cachehits
erzeugen keinen neuen Wetterempfang. Die Originalantwort wird nicht verändert.

## 2. Tagesstartwerte getrennt von Lernhistorie erhalten

`prognose_tag_0` bleibt die tatsächlich vor lokalem Tagesbeginn ausgegebene
vollständige Prognose. Sie wird nie aus aktuellem Wetter oder Istenergie nachgebaut.
Die zusätzliche lokale Verfügbarkeitsabsicherung prüft beim Archivieren neben
`issued_at` auch die tatsächliche Rückkehr des vollständig berechneten Ergebnisses
aus dem Executor, einschließlich der optionalen Shadowberechnung. Beginnt ein
Lauf um 23:59 und endet erst nach lokalem Tagesbeginn, erzeugt er keinen fehlenden
Tagesstartwert und überschreibt keinen vorhandenen Originalwert oder
Administratorimport. Ein späterer zukünftiger Tag bleibt nutzbar. Die lokale
Mitternacht wird mit der Anlagenzeitzone in UTC umgerechnet, auch an beiden
Zeitumstellungstagen.

Dieselbe Verfügbarkeitsgrenze schützt neue Trainingszeilen: Ist ihre Zielzelle
bei Fertigstellung bereits begonnen, wird sie nicht nachträglich als prospektiv
archiviert. Noch nicht begonnene Zellen bleiben nutzbar. `issued_at` und
Leadfeatures behalten ihren ursprünglichen Berechnungsbezug; es wird keine
frühere Verfügbarkeit erfunden und keine bereits begonnene Trainingszelle
nachträglich zugeschnitten. Bestehende historische Datensätze und ihre
Provenienz werden durch diese Schreibsperren nicht umgedeutet.
Im bestehenden festen `history_v2`-Store ergänzt `daily_snapshot_provenance` die
bestehenden `daily_snapshots`; es entstehen keine zusätzlichen Storedateien.

Pro Tag enthält die Provenienz Schema 1, ursprünglichen vollen und physischen
Konfigurationshash, Zeitzone, ursprüngliche Stufengrenzen und einen Identitätshash
aus Standort, Zeitzone sowie Stufenkennungen und AC-/DC-Ausgangstypen. Numerische
Tagesgrenzen verwenden diese ursprünglichen Grenzen und die echte 23/24/25-Stunden-
Dauer. Der historische Wert darf daher eine später abgesenkte Stufengrenze
überschreiten, ohne als neue Prognose oder Messenergie ausgegeben zu werden.

Bei Dämpfungs-, Horizont-, String-/Leistungs- oder Messquellenänderungen werden
inkompatible Lernarchive, Istintervalle, Anker und Schattentabellen weiterhin nicht
übernommen. Bereits ausgegebene vergangene/heutige Tagesstartwerte bleiben mit
ihrer ursprünglichen Provenienz erhalten, sofern Standort, Zeitzone und
Stufenidentität unverändert sind. Zukünftige Snapshots eines anderen physischen
Konfigurationsstands werden verworfen. Andere Standorte, Zeitzonen oder AC-/DC-
Stufengrenzen werden nicht vermischt. Aufbewahrung: heute und sieben vergangene
lokale Tage sowie aktuelle zukünftige Snapshots; höchstens 32 Snapshots beim Laden.

Ältere Snapshots ohne eigene Provenienz werden nur unter passendem bisherigen
Historienhash übernommen und beim Speichern gekennzeichnet. Ein opaker Altstand
darf keine Provenienz aus der neuen Konfiguration erhalten. Am Tag-0-Sensor zeigen
`forecast_provenance` und `forecast_configuration_changed`, ob der ursprüngliche
Konfigurationsstand vom heutigen abweicht. Das ist keine aktuelle Prognoserevision.

## 3. Bereits verlorenen Originalwert gezielt wiederherstellen

Die Administratoraktion `adaptive_solar.restore_day_start_forecast` importiert
genau **einen fehlenden historischen Tageswert**. Felder:

| Feld | Bedeutung |
| --- | --- |
| `config_entry_id` | Geladener Adaptive-Solar-Eintrag derselben Anlage |
| `day` | Lokales Zieldatum `YYYY-MM-DD`, heute oder höchstens sieben Tage zuvor |
| `snapshot` | Originalobjekt mit genau `issued_at` und `energies`; kWh je Stufenkennung |
| `source_site` | Vollständiges ursprüngliches `site`-Objekt aus dem zugehörigen gesicherten Konfigurationsstand |

Vor Aufruf Originalwert, Ausgabe vor Mitternacht und Originalkonfiguration gegen
ein zusammengehöriges Archiv prüfen. Die Aktion prüft Struktur, Zahlen,
ursprüngliche Tagesgrenzen und gemeinsame Anlagenidentität; sie kann die vom
Administrator erklärte Archivherkunft nicht unabhängig zertifizieren. Die
Provenienz nennt deshalb ausdrücklich `source=operator_restore`.

Die Aktion überschreibt keinen vorhandenen Tag, akzeptiert keine Zukunftswerte,
keine Konfigurationsfremden und keine nach Tagesbeginn ausgegebenen Prognosen.
Sie persistiert nur den Snapshot mit seinen Hashes/ursprünglichen Grenzen, nicht
das übergebene vollständige `source_site`. Lernzeilen, Zähleranker, Optionen,
Geräte, Entity-IDs und Energy-Einstellungen bleiben unverändert. Die Aktion liest
nach dem nativen Speichern die tatsächliche Datei zurück, weil HA manche
Schreibfehler nur protokolliert. Bis zur passenden Rücklesebestätigung bleibt der
Wert für Sensoren unsichtbar; Fehler verwerfen den vorgeschlagenen Import.
Ein fehlerhafter oder nicht schreibbarer Store sperrt die Aktion.

Über die HA-Aktionsoberfläche mit einem Administrator ausführen; keine direkte
Bearbeitung von `.storage` und keine vollständige HA-Backup-Wiederherstellung.
Originalkonfigurationen können private Sensorbindungen/Koordinaten enthalten:
nur lokal verwenden und weder veröffentlichen noch in externe Reviews aufnehmen.

## 4. Nachweise und Upgrade

Regressionen prüfen Nacht/Tag/Dämmerung, beide DST-Wechsel, Polartag/-nacht,
unveränderte Rohantworten und vollständige Tagesabdeckung; außerdem physische
Neukonfiguration, ursprüngliche Energiegrenzen, Persistenz, Importfehler und
Administratorberechtigung. [Release und Prüfstand](../releases/release-0.2.14.md).

Runtimepins und Lernfeaturevertrag bleiben unverändert. Nach HACS-Download Core
einmal neu starten. Vorher Komponentenbytes und Historienstores sichern. Bereits
verlorene Werte erscheinen erst nach explizitem Originalimport; ein Update allein
kennt deren frühere Originalkonfiguration nicht.
