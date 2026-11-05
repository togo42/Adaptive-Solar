# Vollständige Diagnose gespeicherter Schattenfenster

Stand: 05.11.2026, **unveröffentlichte Vorbereitung für AF-036**. Der laufende
Release 0.2.22 und das Dashboard im getrennten HA-Config-Projekt sind dadurch
nicht aktualisiert. Dieser Vertrag ergänzt ausschließlich eine lesende Sicht;
keine Lern-, Freigabe- oder Prognoseregel wird geändert.

## 1. Öffentliche Schnittstelle

Der bestehende Prognosedatenstatus-Sensor und die redigierte
Integrationsdiagnose liefern zusätzlich je Ausgangsstufe:

`attributes.learning[stage_id].beam_shade_windows`

In der Integrationsdiagnose entfällt das Präfix `attributes`. Der bisherige
Block `beam_shade` mit dem **aktuellen** Sonnenfenster bleibt unverändert.
Die neue Liste enthält alle **aktuell gespeicherten** Fenster der ausgewählten
Stufe, auch noch nicht freigegebene, veraltete und nur mit unqualifizierten
Altdaten belegte Fenster. Sie enthält keine erfundenen leeren Rasterzellen.

Synthetisches Beispiel mit genau einem freigegebenen Fenster:

```json
{
  "schema_version": 1,
  "evaluated_at": "2026-06-21T10:00:00+00:00",
  "scope": "stored_solar_windows",
  "azimuth_step_deg": 10,
  "elevation_step_deg": 5,
  "max_items": 648,
  "total": 1,
  "truncated": false,
  "filled_bins": 1,
  "policy": {
    "min_samples": 5,
    "min_days": 2,
    "max_age_days": 45,
    "max_daily_mad": 0.15
  },
  "items": [
    {
      "azimuth_bin_deg": 180,
      "elevation_bin_deg": 40,
      "transmittance": 0.6,
      "candidate_transmittance": 0.6,
      "daily_mad": 0.0,
      "samples": 5,
      "days": 2,
      "excluded_time_samples": 0,
      "newest_sample_age_days": 0.0,
      "release_reason": "qualified",
      "released": true,
      "stored_samples": 5,
      "expired_samples": 0,
      "unavailable_samples": 0,
      "unqualified_legacy_samples": 0
    }
  ]
}
```

## 2. Umfang und Zählung

| Feld | Bedeutung |
| --- | --- |
| `schema_version` | Integer `1`; unbekannte Versionen nicht als dieselbe Schnittstelle auslegen. |
| `evaluated_at` | Expliziter UTC-ISO-Zeitpunkt der Schattenauswertung dieses Coordinatorlaufs. Alle Fenster verwenden denselben Zeitpunkt und dieselbe Tabellenkopie. Nicht mit dem eventuell älteren Fitzeitpunkt der Ablehnungsdiagnose verwechseln. |
| `scope` | Fest `stored_solar_windows`: Sicht auf vorhandene Tabellenzellen, keine vollständige Lernhistorie seit Installation. |
| `azimuth_step_deg`, `elevation_step_deg` | Rasterbreiten 10° und 5°. Koordinaten der Einträge sind Untergrenzen; Bereiche sind links geschlossen und rechts offen. |
| `max_items` | Höchstens 648 unterschiedliche Fenster je Stufe: 36 Azimut- × 18 Höhenzellen. |
| `total`, `items`, `truncated` | `total == items.length`; alle vorhandenen Zellen, numerisch nach Azimut und dann Höhe aufsteigend sortiert. `truncated` ist in Version 1 immer `false`. |
| `filled_bins` | Summe der Einträge mit `released == true`, identisch zur vorhandenen stufenweiten Zählung zum selben Zeitpunkt. Nicht die Zahl aller gespeicherten Fenster. |
| `policy` | Aktuelle Mindestproben-/Tageszahl, Altersgrenze und maximale Tagesmedian-MAD für die Tabellenfreigabe; keine Genauigkeits- oder physische Quellenqualifikation. Die zusätzlichen Aufnahmegates bleiben separat bestehen. |

Eine leere, aber gelieferte Liste (`total: 0`) bedeutet: Diese Stufe hat im
vorhandenen Tabellenstand keine gespeicherten Fenster. Ein **fehlender Block**
bedeutet dagegen, dass die verwendete Producer-Version diesen Vertrag nicht
liefert oder noch kein erfolgreicher Ausgabestand vorliegt. Ein fehlender
Block darf nicht als leere Tabelle interpretiert werden.

## 3. Aussage je Fenster

| Feld | Bedeutung |
| --- | --- |
| `azimuth_bin_deg`, `elevation_bin_deg` | Untergrenzen des gespeicherten Sonnenstandsfensters; beispielsweise `[180°,190°)` und `[40°,45°)`. Keine Uhrzeitintervalle. |
| `transmittance` | Tatsächlich freigegebener Direktstrahlfaktor zum Auswertungszeitpunkt; sonst neutraler Fallback `1.0`. Gilt gemeinsam für die Ausgangsstufe, nicht als gemessener Einzelstringverlust oder Gesamtleistungsverlust. |
| `released`, `release_reason` | Freigabe und Grund nach denselben zeitlichen, Mindesthistorien- und Stabilitätsregeln wie die bestehende Tabellenanwendung. |
| `candidate_transmittance`, `daily_mad` | Kandidat aus gleichgewichteten Tagesmedianen und deren MAD. Beide `null`, wenn keine zeitlich verwendbare Schema-3-Probe vorhanden ist; keine erfundene neutrale Schätzung aus ausschließlich alten/fehlenden Belegen. |
| `samples`, `days` | Verwendbare verschiedene UTC-Viertelstunden und deren verschiedene UTC-Beobachtungstage. Keine Anzahl von Polls oder Prognoseausgaben. |
| `stored_samples` | Aktuell im Schema-3-Puffer dieser Zelle gespeicherte Proben, höchstens 24. Unqualifizierte Altdaten sind darin nicht enthalten. |
| `expired_samples` | Schema-3-Proben mit Beobachtungszeit **vor** `evaluated_at - 45 Tage`. Die Grenze selbst ist noch zulässig. |
| `unavailable_samples` | Nicht bereits veraltete Schema-3-Proben, deren Beobachtungs- oder tatsächlicher Verfügbarkeitszeitpunkt nach `evaluated_at` liegt. |
| `excluded_time_samples` | `expired_samples + unavailable_samples`; zugleich `stored_samples - samples`. |
| `newest_sample_age_days` | Alter der jüngsten verwendbaren Beobachtung als Zahl in UTC-Tagen, sonst `null`. Ein Auslesen erneuert dieses Alter nicht. |
| `unqualified_legacy_samples` | Ausschließlich die Altdaten **dieser Zelle** ohne verifizierbare Beobachtungs-/Verfügbarkeitszeiten. Anders als der bisherige gleichnamige Wert unter `beam_shade` ist dies keine stufenweite Summe. Diese Proben tragen niemals zu `samples`, `days` oder einer Freigabe bei. |

`release_reason` ist `qualified`, `insufficient_samples`, `insufficient_days`,
`unstable_daily_transmittance` oder `no_release_available_at_as_of`. Die
letzten Aufnahmeablehnungen wie `at_cap` oder `low_beam` bleiben im bestehenden
aktuellen `beam_shade.last_rejection`; sie sind nicht als angebliche letzte
Entscheidung jeder anderen Zelle kopiert.

**100 % Durchlass ist nicht gleich ungelernt:** Ein freigegebenes neutrales
Fenster hat `released: true`, `transmittance: 1.0`. Ein Fallback hat
`released: false`, ebenfalls Faktor `1.0`. Ein freigegebener Faktor `0.0` ist
ein gültiger Wert und darf nicht zu fehlenden Daten werden. Diffuslicht wird
von diesem Faktor nicht abgesenkt.

Altdatenzellen bleiben über ihren separaten Zähler sichtbar; veraltete Zellen
über `stored_samples` und `expired_samples`. Fehlende Proben werden weder als
Freigabe noch als bewiesene Schattenfreiheit dargestellt. Es erfolgt keine
Nachbarschaftsinterpolation.

## 4. Lesende Projektion und Zeitgrenzen

`BeamShadeTable.window_diagnostics()` bewertet jedes gespeicherte Fenster
einmal; sie ruft nicht für jede Zelle erneut die stufenweite Zählung auf.
Die Anzahl der Proben und Freigabeereignisse je Zelle ist durch den bestehenden
Speichervertrag begrenzt. Es werden keine Rohproben, Faktorenzeitreihen oder
Freigabeereignislisten ausgegeben. Rückgabewerte sind von der Tabelle gelöst;
Änderungen an einer zurückgegebenen Liste ändern keinen Lernstand.

Die Projektion erzeugt und aktualisiert keine Freigabe, entfernt keine alten
Proben und schreibt keinen Store. Sie berücksichtigt reale Verfügbarkeit:
`observed_at` liegt innerhalb der Altersgrenze und nicht nach `evaluated_at`,
`available_at <= evaluated_at`, und eine wirksame Freigabe muss bis dahin
tatsächlich existiert haben. Eine gesonderte Altersgrenze für das
Freigabeereignis wird nicht neu eingeführt.

Die Funktion bewertet den **jetzt gespeicherten** Tabellenumfang. Ein älteres
`as_of` rekonstruiert keine inzwischen verdrängten Rohproben und verbirgt nicht
nachträglich die Existenz später hinzugekommener Fenster. Das ist kein Ersatz
für den chronologischen Originalarchiv-Replay.

Nachts bleibt die gespeicherte Liste verfügbar, auch wenn das aktuelle
Sonnenfenster unter `beam_shade` leer ist. Ohne Coordinatoraktualisierung
verbleibt der letzte veröffentlichte Snapshot mit seinem echten
`evaluated_at`; kein Frontend soll ihn als frisch berechnete Tabelle ausgeben.

## 5. Erhaltung, Rollout und Rückweg

Unverändert bleiben `beam_shade_v1` mit Speicherschema 3, dessen bisherige Leser,
Konfigurations-/Historien-/Schattenfingerprints und
`learning_feature_contract = beam-shade-table-v1`. Die aktuelle
`status_for()`-Schnittstelle und die archivierten Schattenentscheidungen bleiben
unverändert. Die neue Sicht wird ausschließlich als Geschwisterblock im
Lernstatus aufgebaut, nicht in die archivierten Entscheidungsobjekte injiziert.
Keine Änderung an Fit-Eingaben, Freigabegates, Modellanwendung, Forecasts,
Messintervallen oder Tagesstart-Snapshots ist beabsichtigt.

Der ganze `learning`-Block ist bereits von der regulären Recorderaufzeichnung
ausgenommen. Es gibt keine neue Entität, keinen Dienst, keine Option, keinen
zusätzlichen Wetterabruf und keine neue persistente Tabelle. Die Erweiterung
setzt keinen Lernstand zurück und erfordert keine Datenmigration. Bei einem
späteren normalen Neustart werden flüchtige Fits wie bisher aus der erhaltenen
validen Lernbasis aufgebaut.

**Die Softwareherkunft ändert sich trotzdem.** Der Producerhash umfasst alle
Pythondateien der Integration. Vor einer später separat beauftragten
Installation eine noch offene v2-Quellenperiode am tatsächlichen UTC-Cutover
halb offen schließen, bevor sich Dateien oder Laufzeit ändern. Alte Pins,
Originale und Qualifikationsbelege unverändert erhalten; neue Pins nur in
gesondert geprüften neuen Perioden verwenden. Eine alte Bindung ungeprüft über
den Wechsel fortzuführen kann ihre historische Freigabe widerrufen, obwohl
die Originaldateien noch existieren. Siehe
[Upgradegrenzen](../releases/release-0.2.22.md#upgrade-von-0221-und-rückweg).

Für einen reinen Code-Rückweg ist kein Lern-/Archivrestore vorgesehen: alte
geprüfte Komponentenbytes weiter mit dem unveränderten Store verwenden;
vorher den realen Quellwechsel und die Quellenbindungen ebenfalls sauber
abgrenzen. Originalarchive und fortgeschriebene Checkpoints nicht aus einer
alten Sicherung überschreiben. Der Rückweg im Dashboard muss einen dann
fehlenden Diagnoseblock ausdrücklich als nicht verfügbar behandeln.

## 6. Getrennte Folgearbeiten

Die Fensterkarte selbst gehört zum HA-Config-Projekt und ist hier weder
implementiert noch installiert. AF-036 darf dort nicht allein wegen dieses
vorbereiteten Producer-Vertrags als produktiv erledigt gelten. Ebenso nicht
enthalten ist eine positive Zeitliste angenommener ML-Zielintervalle. Diese
kann nicht aus den bestehenden Ablehnungslisten abgeleitet werden.

Die Prüfungen müssen neben Fenstersemantik auch Nichtmutation, unveränderte
Persistenz und Modell-/Archiventscheidungen abdecken. Tests und Reviews sind
keine Aussage über physische Messquellen oder bessere Prognosen.

## 7. Lokaler Vorbereitungsnachweis

Die Implementierung ergänzt nur `core/shading.py` und genau einen
Geschwistereintrag im Coordinator-Lernstatus. Ein AST-Abgleich gegen den
Ausgangsstand `d585258` bestätigt alle 14 bisherigen Methoden von
`BeamShadeTable` unverändert; insbesondere `status_for()`, `to_dict()` und
`from_dict()`. Außerhalb des einen neuen Diagnoseeintrags ist auch der
Coordinator-AST unverändert. Fingerprint-, Sensor-, Diagnose-, Provenienz-,
Schattenentscheidungs-, Schattenreplay- und Learnerdateien bleiben bytegleich.

29 neue Verhaltenstests in `test_shade_window_diagnostics.py` und
`test_ha_shade_window_diagnostics.py` prüfen auch echtes HA-Setup/Reload,
stufengetrennte Vollständigkeit, beide DST-Übergänge, Schema-3-/Legacyerhaltung,
die Rückgabeisolation und unveränderte Modell-/Fit-/Replayeingaben. Der
synthetische JSON-Vertrag oben wurde gegen eine tatsächlich berechnete
Projektion abgeglichen. Ein vollständig belegtes 648-Fenster-Beispiel mit
Faktor 0,6 belegt 212.566 Bytes kompakt serialisierte Diagnostik je Stufe;
das ist eine Beispielmessung, keine allgemeine Byteobergrenze.

Getrennte Subagenten prüften Datenvertrag, Tests, Dokumentation und anschließend
den integrierten Diff. Der unabhängige fokussierte Nachreview meldet keine
Befunde; seine 219 gezielten Tests bestanden. Das ist keine neue externe
Gesamtquellabnahme. Weder Veröffentlichung noch Merge nach `main`,
HACS-/Archivhostinstallation, Neustart oder Quellenbindungsänderung wurden
ausgeführt. Der laufende Pilot bleibt unberührt.

Abschließende lokale Gesamtsuite unter Python 3.14.4 und echtem HA Core
2026.10.4: **3.104 Tests bestanden, zwei ausgelassen**, kombinierte
Zeilen-/Zweigabdeckung **91,49 %** bei unverändertem 90-%-Gate. Die zwei
Auslassungen sind ausschließlich die optionalen Positiv-/Konflikttests mit
explizit bereitzustellendem realem Rust-Qualitätskernel; dieser wurde hier nicht
angefordert. Keine ausgelassene HA-Prüfung wird als bestanden gewertet.
30 SQLite-`ResourceWarning`-Meldungen zu nicht geschlossenen Verbindungen
wurden nicht unterdrückt; diese Vorbereitung behebt diese Testhygiene nicht.
Ruff, `pip check`, Diff-Whitespaceprüfung und das Rendering der sechs
betroffenen Markdowndateien einschließlich 171 lokaler Verweise bestanden.
