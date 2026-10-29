# Zeitlich zuordenbare Ablehnungsdiagnose

Stand: 27.10.2026. Seit Version 0.2.13 verfügbar; Veröffentlichung und
HA-Rollout sind im [Prüfstand](../entwicklung/pruefnachweise.md) separat nachgewiesen.
Die Diagnose beschreibt vorhandene Entscheidungen; Prognosen, Messlabels, Schwellenwerte und ML-Freigabe ändern
sich dadurch nicht. Die separat vorbereitete Anzeige gehört zum Repository
HA-Config und wird hier nicht verändert.

## 1. Schnittstelle

Der bestehende Prognosedatenstatus-Sensor und die redigierte Integrationsdiagnose
liefern je Ausgangsstufe:

`attributes.learning[stage_id].training_quality.rejection_details`

```json
{
  "schema_version": 1,
  "evaluated_at": "2026-06-01T12:00:00.000000+00:00",
  "targets": {"total": 0, "truncated": false, "items": []},
  "rows": {"total": 0, "truncated": false, "items": []}
}
```

Beide Gruppen sind immer vorhanden. `evaluated_at` ist der echte Cutoff des
zuletzt ausgeführten Fits, kein historischer Ablehnungszeitpunkt. Die Diagnose
ist eine Sicht auf dessen vorhandenen Archivumfang, kein Ereignisjournal.

| Gruppe | Inhalt und Zählung |
| --- | --- |
| `targets` | Abgeschlossene eindeutige ursprüngliche Zielintervalle aus `join_training()`. `total` entspricht `alignment.rejected_target_cells`. |
| `rows` | Alle schon im stufenweiten Learner-Zähler `rejected_rows` enthaltenen Ablehnungen. `total` entspricht diesem Rohzähler; bei leerer Historie ohne Learner-Eintrag ausdrücklich null. |

Zieleinträge tragen `start`, `end`, `reasons`; Zeilen zusätzlich `issued_at` und
`regime` (`nwp`, `ghi`, `unknown`). Zeiten sind UTC-ISO-Strings mit explizitem
Offset. Nicht gültige oder zeitzonenlose Originalzeiten von Zeilen erscheinen
als JSON `null`, niemals als erfundener Zeitpunkt. Wohlgeformte, aber zeitlich
unzulässige Originalwerte bleiben sichtbar. Die Start-/Endwerte einer Zeile
beschreiben den tatsächlichen `TrainingSample`-Messblock, die eines Ziels die
ursprüngliche Prognosezelle.

Je Gruppe werden höchstens 50 eindeutige Schlüssel gehalten und ausgegeben,
neueste Zielenden zuerst. Tie-Breaker: Beginn, Ausgabezeit, Regime, jeweils
absteigend; unbekannte Zeiten zuletzt. Zielschlüssel sind `(start, end)`,
Zeilenschlüssel `(start, end, issued_at, regime)` innerhalb der Stufe. Identische
Schlüssel vereinigen ihre sortierten, eindeutigen Gründe. Der Rohzähler bleibt
unverändert; `truncated` ist exakt `total > items.length`, auch wenn gleiche
Zeilen zusammengefasst wurden. Es gibt keine Auswahl nach Ertrag oder Modellfehler.

## 2. Gründe aus den Entscheidungsstellen

Zielgründe stammen aus demselben Join-Outcomes-Snapshot wie die vorhandenen
Summen. Schon eine angenommene Ausgabe genügt, damit ein Ziel nicht abgelehnt
ist. Noch laufende Ziele fehlen in den Ablehnungsdetails. Mehrere Origins oder
Regime vervielfachen das Ziel nicht. Bestehende Join-Codes bleiben erhalten,
beispielsweise `insufficient_measurement_coverage`, `measurement_edge_exceeded`,
`internal_measurement_gap`, `observation_not_yet_available` oder
`stale_beam_shade_baseline`.

Die Learner-Eingangsprüfung selbst liefert in ihrer bisherigen sicheren
Prüfreihenfolge den ersten blockierenden Code; es gibt keinen zweiten
nachgeschalteten Klassifizierer:

| Codes | Tatsächliche Prüfung |
| --- | --- |
| `invalid_issued_at`, `invalid_start`, `invalid_end`, `invalid_observed_at` | Fehlende, ungeeignete oder zeitzonenlose Originalzeit |
| `issued_after_target_start`, `nonpositive_target_duration` | Prospektive Ausgabe und positive Intervalllänge |
| `observation_before_target_end`, `observation_not_yet_available` | Fertiges Label und tatsächliche Verfügbarkeit bis Cutoff |
| `invalid_measurement_alignment` | Messdauer, Zielzeit, Abdeckung und Randmetadaten |
| `curtailed` | Bereits als abgeregelt markierte Zeile |
| `invalid_feature_vector` | Fehlender/ungeeigneter Vektor oder ungültige Regime-/Feature-Repräsentation |
| `invalid_shade_factor`, `invalid_output_cap` | Bestehende Schattenfaktor- und Ausgangsgrenzenprüfung |
| `invalid_baseline`, `invalid_actual_power` | Nicht endliche Leistungswerte |
| `baseline_out_of_range`, `actual_power_out_of_range` | Bisherige Baseline-/Istleistungsgrenzen einschließlich Toleranzen |
| `nonpositive_sun_elevation`, `negative_lead_time` | Tageslicht und nichtnegative Vorlaufzeit |
| `baseline_feature_mismatch` | Featurebaseline entspricht nicht der Zeilenbaseline |
| `incompatible_shade_baseline` | Bereits im bestehenden Rohzähler enthaltener späterer Schatten-Kompatibilitätsfilter |

Die letzte Kategorie ist eine ausdrücklich abgestimmte Präzisierung des
Startprompts: Der bestehende Rohzähler enthält diese Filterung bereits. Sie zu
verschweigen würde die verlangte Summengleichheit verletzen. Andere spätere
Filter wie widersprüchliche Duplikate, Zielkonflikte, Holdout-Purging und
Validierungs-/Mindesthistoriengates erzeugen keine neuen Detailzeilen und
keine zusätzlichen Rohablehnungen. Unbekanntes Regime wird ausschließlich als
Diagnosewert ausgewiesen und erzeugt kein neues Modellregime.

## 3. Snapshot, Speicher und Grenzen

Ebenfalls ausdrücklich abgestimmt: `alignment` und beide Detailgruppen werden
zusammen mit dem tatsächlichen Fit eingefroren. Bei unveränderter Fitsignatur
bleiben sie einschließlich `evaluated_at` erhalten. Die aktuelle Zählerquelle
unter `meter` und die Schattenfensteranzeige bleiben aktuelle Diagnosen und
tragen nicht diesen historischen Auswertungsanspruch. Der bestehende Fittrigger
(Historienrevision, lokaler Tag, Schattentabellenstand) bleibt unverändert;
ohne neuen Trigger kann der Diagnosesnapshot bis zum nächsten Tag alt bleiben.

Es gibt keine zusätzliche Archivkopie außerhalb der bestehenden begrenzten
Worker-Snapshots, keine persistierten Detaildaten, neuen Recorderreihen,
Dienste oder Netzabfragen. `learning` bleibt ein nicht aufgezeichnetes
Sensorattribut. Neue Details enthalten weder konfigurierte Entity-IDs noch
Standortdaten, Rohfeatures oder Messwerte. Bestehende Diagnose-Redaktion bleibt
erhalten. Ein Eingangsfehler kann wegen der Prüfsequenz spätere Fehler verdecken;
die Detailgruppe verspricht keine vollständige Fehlerliste jeder Zeile.

Verhaltenstests: `tests/test_rejection_details.py`, einschließlich echter
HA-Sensorausgabe und Integrationsdiagnose. Dies ist ein Software-/Transportnachweis,
kein produktiver Dashboardtest oder Beleg verbesserter Prognosegüte.
