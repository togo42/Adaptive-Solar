# Gezielte Archivauswahl auf eingefrorenen Eingaben

Stand: 03.11.2026. Lokaler Messprototyp für eine ausdrücklich gebundene
Archivkopie und Abfrage. Der normale Archivbetrieb verwendet weiterhin den
vollständigen Scan. Es gibt keinen produktiven Cache und keine Aktivierung.
Der gebundene lokale Wiederverwendungsvergleich erfüllt die vorab festgelegten
Entwicklungskriterien. Sein vollständiger Kaltaufbau kostet zusätzliche Zeit;
die Einzelwerte und Amortisierung stehen in der privaten Betriebsdokumentation.

## 1. Zweck und Vertrauensgrenze

Nach der [optimierten Originalvalidierung](performance-originalvalidierung.md)
verbleiben wesentliche Kosten im Originallesen und in dessen Prüfung. Der
Prototyp in [`scripts/frozen_quality_selection.py`](../../scripts/frozen_quality_selection.py)
untersucht, ob sich vollständig irrelevante Batches auslassen lassen.
Ein alter Index oder eine selbst deklarierte Prüfsumme genügt dafür nicht.

`query_from_capture(raw, bindings)` bindet den vollständigen Rohcapture, die
Quellenpolicy, UTC-Zielstunden, Quellen, Policyperioden und Konfigurationsanker.
`build_plan(reader, query)` prüft zunächst **alle** Originaldateien nativ und
gleicht Batch- und Ereignisindex vollständig mit diesen Originalen ab. Gleiche
Wiederholungen in mehreren Batches bleiben möglich; widersprüchliche Sequenzen,
fehlende Originale und falsche Referenzzeiger führen zum Abbruch. Der lesende
Adapter muss aus demselben gepinnten Quellbaum stammen und die eingefrorene
Kopie ohne Storeinitialisierung oder Schreibzugriff öffnen.

Der fertige Plan bindet komprimierte Dateibytes, vollständige SQLite-Datei,
Abfrage, alle öffentlichen Python-/JSON-Quellen des gewählten Quellbaums sowie Pythonversion,
Rekursionsgrenze, Integer-Lesegrenze, JSON-Einstellungen und native Größenlimits.
Sein kanonischer Dokumenthash wird **außerhalb** des Plans festgehalten und
beim Wiederverwenden ausdrücklich übergeben. Readerunterklassen dürfen die
nativen Lese-, Pfad- und Referenzmethoden nicht überschreiben; eigene
Initialisierung und read-only Datenbank-/Lockadapter bleiben möglich.
Ein selbst beigefügter Hash
beweist weder Vollständigkeit noch vertrauenswürdige Herkunft des Plans.

Bei jeder `selection_scope` werden alle komprimierten Originale und der Index
vor und nach der Ableitung erneut gehasht. Ausgewählte Originale und benötigte
Payloadreferenzen durchlaufen weiterhin die native Originalvalidierung.
Geänderte Rohdaten, Policy, Quellen, Runtimegrenzen, zusätzliche oder entfernte
Dateien, Retention oder Indexänderungen machen den Plan ungültig. Ergebnisse
erst nach erfolgreichem Verlassen des Scopes veröffentlichen.

## 2. Auswahlregeln und Fehlerfälle

Für jede gebundene Quelle berücksichtigt die Auswahl:

- Intervalle, die das UTC-Zielfenster überlappen, einschließlich stundenübergreifender Deltas;
- ausdrücklich referenzierte Konfigurationsanker auch außerhalb des Fensters;
- alle Konfigurationsforecasts innerhalb jeder Policyperiode;
- alle Generationen und Wechselrichter als mögliche Gegenbelege;
- unklare oder fehlerhafte Selektionszeiten konservativ durch Einschluss des Batches.

Der Selektor setzt keinen eigenen Empfangszeit- oder `as_of`-Filter. Der
unveränderte Qualitätsverbraucher entscheidet mit seiner tatsächlichen Uhr,
welche Evidenz bereits verfügbar ist. Abhängigkeiten werden weiterhin mit dem
nativen Resolver aufgelöst, auch außerhalb des gewählten Zielfensters;
fehlende oder mehrdeutige Referenzen bleiben Fehler.

Das frühere erfolgreiche Prüfen einer tiefen JSON-Struktur garantiert noch
keine erfolgreiche spätere Prüfung unter einem tieferen Python-Aufrufstack.
Der Kaltaufbau prüft deshalb mit reservierten Aufrufrahmen. Reicht diese
Reserve nicht aus, muss ein flacher nativer Wiederholungsversuch bestehen und
der Batch bleibt zwingend ausgewählt. Bei zu wenig Headroom im späteren
Aufruf fällt die Auswahl auf den vollständigen nativen Scan zurück. Die
Reserve und zusätzliche Marge sind im Plan gebunden. Das schützt die
geprüften nativen und instrumentierten Pfade; beliebig veränderte oder
zusätzlich instrumentierte Reader sind kein freigegebener Planverbraucher.

Der Scope erlaubt ausschließlich die vorgesehenen Leseoperationen und schließt
offene Iteratoren beim Verlassen. Er ist keine Sandbox für fremden Pythoncode.
SQLite wird read-only geöffnet; Symlinks, SQLite-Sidecars und überschrittene
Datei-/Ereignis-/Bytebudgets werden abgelehnt. Gzip-ISIZE dient lediglich der
vorläufigen Ressourceninventur. Die native begrenzte Dekompression bleibt
erforderlich. Ein äußerer Prozess-Timeout ergänzt die Mengenbudgets.

## 3. Messen statt Aufbaukosten verstecken

Kaltaufbau und Wiederverwendung sind getrennte Fälle. Der Kaltaufbau liest und
prüft den vollständigen Satz und kann mehr kosten als eine normale Ableitung.
Ein Wiederverwendungslauf zählt Planlesen, Planhash, Queryaufbau und beide
vollständigen Byteprüfungen zur inneren Laufzeit. Der Messhelfer akzeptiert
dafür zusätzlich:

```text
--selection-plan PATH --selection-plan-sha256 CANONICAL_DOCUMENT_SHA256
```

Das ist der kanonische Dokumenthash aus `plan_sha256(plan)`, kein Hash der
eingerückten JSON-Datei. Der Messhelfer bindet zusätzlich den tatsächlichen
Dateihash in seinem Eingabemanifest. Alle Module einschließlich Selektor
müssen aus demselben frischen, cachefreien Quellbaum geladen werden. Ohne
diese Optionen verwendet der Helfer den bisherigen vollständigen Reader.

Für einen Vergleich dieselben eingefrorenen Originale, Rohcapture, Policy,
Qualitätsmodule, Interpreter und Messhelfer verwenden. Zwei gewöhnliche Läufe
je Arm in der Reihenfolge Vollscan–Auswahl–Auswahl–Vollscan ergänzen eine
positive Kontrolle. Keine Tests oder anderen Benchmarks parallel starten.
Phasenläufe bleiben getrennte Diagnostik. Der genaue Ablauf steht in der
[Messanleitung](performance-qualitaetsphasen.md).

Vor Ergebnisauswertung festgelegte Entwicklungskriterien: mindestens 10 %
weniger Wall- und CPU-Zeit beim vollständigen lokalen Wiederverwendungsfall,
höchstens 10 % höherer Spitzen-RAM und höchstens 10 % höhere Kontroll-Wall- und CPU-Zeit.
Unveränderte fachliche Entscheidungen, Originalreferenzen, Konfigurationsbelege
und Eingabebytes sind unabhängig davon zwingend. Bei wenigen Läufen keine
statistische Absicherung oder p95 behaupten. Konkrete Datenmengen, Zeiten und
Prüfsummen bleiben in der privaten Betriebsdokumentation.

Auch eine schnelle Wiederverwendung ist kein Nachweis für einen schnelleren
ersten Durchlauf. Der Break-even muss die einmaligen Kaltaufbaukosten enthalten.
Im geprüften lokalen Satz war Aufbau plus erste Auswertung langsamer als der
optimierte Vollscan; erst mehrere identische Auswertungen amortisierten den Aufbau.
Neue Archivdateien oder ein bewegtes Zielfenster invalidieren diesen exakten
Plan. Ein fortlaufend gepflegter, abfrageunabhängiger Validierungskatalog ist
eine eigene, hier nicht implementierte Architekturänderung.

## 4. Weiterer Rechenaufwand

Die mögliche Ersparnis hängt von Archivalter, Batchzuschnitt und Policyperioden
ab. Enthalten die meisten Batches relevante Evidenz, begrenzt das bereits den
Gewinn durch diese Auswahl. Ein [Rustbaustein](performance-rust.md) könnte
zusätzlich Python-Schleifen und Objektaufbereitung bündeln. Der folgende
[Rustversuch](performance-rust-probe.md) beginnt mit der Originalvalidierung
und verwendet keinen zuvor aufgebauten Auswahlplan. Weder der Plan noch diese Bewertung
ändert Quellenqualifikation, Prognosegüte oder produktive Freigaben.
