# Validierung und Genauigkeitsnachweis

Stand: 25.10.2026. Überlegenheit gegenüber Helios Forecast/Open-Meteo Solar bleibt offen. Konsolidiert aus dem lokal archivierten Vorgänger `artifacts/releases/0.2.5-blocked/source/docs/validierung.md`; das Archiv wird nicht veröffentlicht.

## 1. Nachweisgrenzen

Physik-/Zeittests, synthetisches Schattenlernen und gebundener Grok-Review prüfen Mechanismen, keine reale Verbesserung. Echtes HA im Test belegt APIs, keine produktive Stabilität. Musl-Parität prüft die Binärbasis; nativer Setupdialog nur Paketmetadaten/Form, nicht alle ML-Imports/Fit oder einen Forecast-Lifecycle. [Abgrenzung](haos-installation.md#6-getrennte-nachweise).

Nur fair archivierte prospektive Prognosen belegen Güte der geprüften Periode, keine allgemeine Saison-/Anlagengültigkeit.

## 2. Messplan vor Beginn einfrieren

Identische Strings, nominelle Grenzen und AC-/DC-Messpunkte für alle Anbieter. Gemeinsamer DC-Regler: originale synchrone Array-Viertelstunden addieren/gemeinsam begrenzen, danach vollständig zu Stunden aggregieren; Stundenclip ist nicht gleichwertig, native Arraylimits bleiben sichtbar. Versionen, Konfiguration/Sensorzuordnung, Ausgabezeiten, Zeitraum und Hashes vorab lokal festhalten; private Daten außerhalb Git/Review.

Je Stufe: Day-ahead zur festen lokalen Vortagszeit, Tag2/3 ebenso, Resttag z.B.09/12/15 Uhr; längere Horizonte nur bei gemeinsamer Abdeckung. Istenergie auf denselben Intervallen, Lücken/Abregelung kennzeichnen. `issued_at`, Ziel und tatsächliche Archivierungszeit bewahren. Nachträglich gelesene Zustände, aktuelle Wetterstände, ERA5/Rekonstruktion sind keine damalige Prognose. Reset/unabgedeckte Zeit bleibt fehlend.

Capture rechtzeitig **vor** festem Cutoff starten: vollständiger Gruppenempfang entscheidet, nicht Prozessstart. Lokaler Preflight prüft nur deklarierte Messgrenzenbelege/Zeitbudget, keine Quellenqualität. Integrierte Leistung muss als Energieschätzung qualifiziert werden. [Aufnahmeablauf](benchmark-aufnahme.md).

Aufwärmphase/primäre Prüfperiode vorher festlegen. Physikfallback gehört zur bewerteten Politik; späteres ML darf frühe Fehler nicht aus der Kohorte entfernen. Primäre Annahmeauswertung einmal auf eingefrorenen Eingaben; laufende deskriptive Diagnose erlaubt. Tägliches Signifikanztesten bis zum Erfolg braucht eine vorher festgelegte sequentielle Fehlerkontrolle.

## 3. Vorläufige Annahmekriterien

Mindestens **30 vollständige gepaarte Zieltage je Stufe/Horizont**; bei einförmigem Wetter verlängern, Ausfälle zusätzlich zur Paarungsmenge ausweisen. Eine Saison belegt kein Ganzjahr.

Primär Tages-/Resttagenergie-MAE(kWh), zusätzlich dauergewichtete Leistungs-MAE/RMSE(W), Energie-Bias/Abdeckung nach Stufe/Horizont; Tageslicht getrennt von Nacht. Intervallaggregate zählen deklarierte Forecasttasks, nicht unabhängige oder einmalige physische Zielstunden. Gesamtwerte dürfen Einzelverschlechterung nicht verdecken.

Vor Sichtung der Daten bestätigen/einfrieren:

- Mindestens 5% niedrigere Energie-MAE gegen **beide** Referenzen in priorisierten Horizonten.
- Keine Verschlechterung über 2% an einer Stufe, kein größerer absoluter Energie-Bias.
- Je vorab deklariertem Stufen-Horizont-Stratum **und Referenz** mindestens 60% gewonnene vollständige Zieltage; Gleichstand kein Sieg. Nur vollständige geplante Origins ergeben deren mittleren Fehler/eine Tagesstimme, keine gepoolten Stratumfehler.

`--bootstrap`: Policy `paired-target-day-bootstrap-v1`, gemeinsame vollständige Tagesblöcke aller deklarierten Strata/beider Referenzen, mindestens30 gemeinsam vollständige Tage, nominal95% Familienkonfidenz/Bonferroni. Annahme verlangt je Stratum 5% Skill selbst an der unteren Intervallgrenze und strikt negative obere MAE-Differenzgrenze; deskriptives Gate bleibt zusätzlich. Origins desselben Zieltags werden gemeinsam resampelt. Ohne Bootstrap: `statistical_acceptance=not_evaluated`.

Diese Approximation setzt austauschbare, repräsentative Tagesblöcke voraus, modelliert keine Persistenz zwischen Tagen. Saison, Herkunft und Messgrenze bleiben eigene Nachweise. Interne ML-Validierung ist kein externer Benchmark; empirische Bänder ohne unabhängigen Nachweis keine behaupteten P10/P90. [Defaults/CLI und Ergebnisinterpretation](benchmark-aufnahme.md#6-ergebnis-interpretieren).

## 4. Lokale Prüfung und Review

Normale Paketinstallation/Testbefehle: [README](../README.md#entwicklung). PEP660-Editable kann HAs Namespace-Loader abbrechen; `pythonpath=["."]` nutzt Repositoryquellen, Paketbytes separat prüfen. Lokale Exportvorprüfung:

```bash
.venv/bin/python scripts/review_grok.py --prepare-only
```

Ohne Prepare startet der angeforderte Review nach internem Pre-Review; z.B. `--timeout 3600` (Standard1800 s, Obergrenze3600 s). Deadline ist kein Review; denselben laufenden Prozess bis Ende beobachten. ESS-Grundlage: `AGENTS.md`/`scripts/ai_review.sh`, gelesen24.10.2026. Fester `grok-4.7` mit explizitem `--reasoning-effort high`; Lesemodus, Tools/Web/Memory/Subagenten aus, ein echter Abschlussturn mit `--verbatim` (exakte Flags im [Helfer](../scripts/review_grok.py)).

Standard bleibt `--scope all --transport single`: neue Sitzung mit allen aktuellen öffentlichen Original-UTF8-Bytes/Dateipfaden, einschließlich endungsloser `LICENSE`-Dateien. Binäre Markenbilder sind außerhalb der Textprüfung. Receipt bindet SHA, Länge und Byteoffset je Datei; kein Kontextkürzen/Quellzeilennummerieren. Über 1.250.000 Bytes Abbruch vor CLI; Bytecap garantiert kein Kontextfenster. `chunks`/ACKs allein belegen keine Retention.

Die Byteobergrenze wurde für 0.2.11 vor einem neuen Review von 1.020.000 auf
1.250.000 angehoben, da der vollständige Quellumfang einschließlich beider
GPL-Lizenzkopien rund 1,14 MB umfasst. Das ist ausschließlich ein lokales
Transportbudget. [Providerdokumentation](https://docs.x.ai/developers/grok-4-7)
und native Modellliste nennen bis zu 500.000 Tokens; der CLI-Default kann geringer
sein. Weder eine Byte-/Tokenschätzung noch dieser größere Vorprüfwert erlaubt
Compaction oder ausgelassene Quellen. Sämtliche nachfolgenden nativen Inhalts-,
Abschluss- und Identitätsprüfungen bleiben unverändert; ein gekürzter Lauf ist ungültig.
Die Obergrenze wird zusätzlich im neuen Receipt gespeichert. Globale CLI-/Modell-
Konfigurationen werden für den Review nicht verändert.

**Expliziter Implementierungsreview mit unverändertem Forschungsbezug:** Wenn ältere Forschung bereits vollständig geprüft wurde, ist folgende Alternative zulässig:

```bash
.venv/bin/python scripts/review_grok.py --scope implementation --transport single \
  --reference-receipt reviews/private/ACCEPTED_ALL/receipt.json --prepare-only
```

Nur diese feste Liste darf dabei textlich fehlen: `solar-prognose-ml-recherche.md`, `solar-prognosemodelle-zusammenfassung.md`, `solar_ml_research.md`, `ensemble_hybrid_solar_forecasting.md`, `solarprognose_datenquellen_feature_engineering.md`, `solarstrahlungsprognose_recherche.md`. Keine frei wählbaren Ausschlüsse. Alle anderen aktuellen Implementierungs-, Test-, Dokumentations- und Helferdateien bleiben vollständig und mit Originalbyteoffsets im Prompt. Dieser Lauf ist **kein erneuter Volltextreview des gesamten Repositories** und behauptet keine erneute Lektüre der sechs Forschungstexte; Umfang und geerbte Hashbezüge stehen ausdrücklich im Prompt.

Jede Forschungsdatei muss bytegleich zur Referenz sein. Vor jeglichem Grok-CLI-Aufruf werden `accepted`, `all` (bei älteren Receipts ohne Scopefeld der damalige vollständige Standard), `single`, Modellwahl/CLI-Pfad/-Bytes/-Versionsbeleg, ein Exit0-Call mit strikten Flags, vollständiger Payload/Manifest/Prompt, Stdout-/Stderr-/Reviewhash und `mergeable` ohne Findings erneut geprüft. Dazu liest `audit_context` ausschließlich die konkrete native Referenzsession: exakte Promptbytes, erfolgreicher `end_turn`, keine Compaction/Tools/Hintergrundaufgaben, native Summary mit `current_model_id=grok-4.7`/`reasoning_effort=high`, passende Modellkennung und je Turn `modelCalls=1`/`numTurns=1`. Die native Endantwort muss kanonisch als striktes Review-JSON mit Stdout und `review.json` übereinstimmen. Alte Calls ohne Effortflag brauchen denselben frischen nativen High-Beleg. Blocked/kompaktierte/manipulierte/unvollständige Referenzen sind unbrauchbar; Referenzketten aus Implementierungsreviews sind verboten. Forschungsdrift verlangt einen neuen gültigen `all`/`single`-Beleg oder Abbruch.

Im neuen Receipt sind `files`/`file_manifest` die tatsächlich eingebetteten Originale, `reference_only_files` die sechs Forschungs-SHAs und `workspace_files` der vollständige aktuelle Scope einschließlich Forschung. `reference` bindet Referenzreceipt, Artefakte, Payload, Review, CLI und native Kontext-/Summary-/Antwortbelege. Historische CLI-Identität folgt dem gespeicherten realen Pfad/Hash, nicht einem inzwischen aktualisierten Aufrufalias; neue Calls binden ihre eigene aktuelle CLI. Der Prompt erhält nur öffentliche Dateinamen/Hashes, keine privaten Sitzungsinhalte oder Artefaktpfade. Zum Abschluss werden gesamter Workspace, CLI, Payload/Prompts und Referenz erneut unverändert nachgewiesen. Der Scope reduziert doppelte historische Texte, nicht den aktuellen Implementierungsumfang; auch er verspricht kein ausreichendes Kontextfenster. Enthaltene offene Planungs-/Brandingtexte behaupten keine implementierten Funktionen und der Review erteilt keine Implementierungsfreigabe. PNG-Logo-Rendering gehört nicht zur textlichen Fachprüfung.

Nur Kindprozesse: `GROK_AUTO_COMPACT_THRESHOLD_PERCENT=100`, Auto-Updater aus; kein NoCompact-Schalter/keine globale Konfigurationsänderung. Ausschließlich konkrete neue `updates.jsonl`: exakte gesendete Benutzerbytes, je Prompt eindeutiger erfolgreicher `end_turn`. Compaction/Tools/aktive Hintergrundaufgaben, unbekannte Ereignisse oder fehlende/mehrdeutige Metadaten verhindern `accepted`.

Finales striktes JSON/nativer Exit, unveränderte Quellen/CLI/Prompts sind Pflicht. Auch im neuen Lauf werden native High-/Modell-/Ein-Turn-Belege und die tatsächliche Endantwort geprüft. ACK, partielles Urteil oder `mergeable` allein genügen nicht. Findings beheben/frisch reviewen; versionsgebundener Audit scheitert bei unbekanntem Format geschlossen. Receipts unter ignoriertem `reviews/private/`, veröffentlichter Nachweis nennt Scope/Bindung/Audit/Datum/Ergebnis/Grenzen. ESS-Deploy-/Node-RED-Regeln gelten hier nicht.

## 5. Offene reale Schritte

Nach Tests/Review: private Zuordnung/Installationsumfang freigeben, reale Laufzeit/Darstellung prüfen, Archive erfassen und eingefrorene Messperiode auswerten. Bis dahin bleibt „besser als beide“ offen.
