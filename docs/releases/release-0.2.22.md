# Adaptive Solar 0.2.22

Stand: 04.11.2026, **Releasevorbereitung** auf dem korrigierten Funktionsstand
`f1c7d9b2417cbad934ea082907c0ff7a498d1e20`. Veröffentlichung, Prüfung der
Releaseartefakte und anschließende HACS-/HA-Abnahme stehen noch aus.

## Änderungen gegenüber 0.2.21

### HA-Setup, Formulare und gespeicherte Tagesstartwerte

- Scheitert das Setup nach der Plattformweitergabe, werden Plattformen,
  Messlistener, Optionslistener und Dienstbesitz unabhängig bereinigt. Eine
  teilfertige Schreibfreigabe wird vor den Cleanup-Awaits widerrufen; ein erneuter
  Versuch beginnt mit einer aktiven Instanz. Ein Cleanupfehler verdeckt nicht
  die ursprüngliche Setupausnahme. Registry-/Restore-Platzhalter bleiben erhalten.
- Eine leere Wettermodellwahl erhält einen eigenen Formularfehler. Numerische
  Standorteingaben werden vor Änderung eines laufenden Entwurfs geprüft;
  die native Schemaprüfung bleibt erhalten.
- Tagessummen und jede gespeicherte Tagesstart-Kurvenzelle werden gegen die
  **ursprüngliche** Ausgangsgrenze und ihre echte UTC-Dauer geprüft. Die bisherige
  zehnprozentige Marge für Prognosesnapshots entfällt; ausschließlich numerische
  Rundung mit absoluter/relativer Toleranz `1e-12` bleibt erlaubt. Das gilt auch
  an 23-/25-Stunden-Tagen. Die Plausibilitätsmarge echter Istintervalle bleibt
  unverändert. [Import- und Erhaltungsvertrag](../technik/forecast-repairs.md).

### Schattenlernen und flüchtiger Leistungsnowcast

Der optionale Export ergänzt `shade_learning.measurement_valid_since` je Stufe
mit konfigurierter Messgültigkeitsquelle. Der Replay prüft den tatsächlich
überwachten Phasenbeginn zusammen mit Rohzustand und Leistungsbericht. Eine
ungesperrte Probe muss streng nach dieser Grenze liegen. Monitoringstart,
Wiederfreigabe aus einem restaurierten Zustand und erkannte Unterbrechungen
bleiben dadurch vom bloß aktuellen `on` unterscheidbar; wiederholtes gültiges
`on` oder reine Attributänderungen beginnen keine neue Phase.
[Messgültigkeit und Legacygrenze](../technik/measurement-validity.md).

Der gemeinsame Schattenlernschritt weist Leistung ab 98 Prozent der Stufengrenze
auch bei falsch gesetztem Kontrollflag zurück. Im optionalen Beobachtungsfallback
ersetzt eine neuere ausdrücklich klare Leistung ältere ungültige Berichte;
gleichzeitige oder spätere aktuelle Sperrbelege bleiben wirksam. Fehlt eine Stufe
im aktuellen Phasenmapping, verwirft der Nowcast auch deren gespeicherten Verlauf.
[Physik-/Schattenoptionen](../technik/physics-learning-options.md).

Der frühe Bias-Shadow prüft zusätzlich die gemeinsame Spannweite aller
Trainings-/Holdoutfaktoren gegen `0,10`. Die Faktoren `0,40` und `0,60` können
daher nicht mehr allein über einen mittleren Anker `0,50` zusammen freigegeben
werden. Dies betrifft ausschließlich den separaten Shadow-/Vergleichsarm;
veröffentlichte operative Forecastpunkte werden dadurch nicht verändert.
[Shadowvertrag](../technik/early-bias-shadow.md).

### Messdaten-, Qualitäts- und Auswertungsgrenzen

- `TrainingSample` verlangt bereits beim Aufbau `issued_at <= start` und
  `observed_at >= end`. Join und Fit behalten ihre zusätzlichen Gates. Die
  Originalintegration verwirft ungültige Baselines einschließlich Boolean,
  nichtendlichen und übergroßen Zahlen.
- Der Offline-Qualitätsadapter filtert zeitlich noch nicht verfügbare und für
  die Ziel-/Bindungsmenge fremde Deltas vor der semantischen Intervallprüfung.
  Die vollständigen gelieferten Originale bleiben integritäts- und hashgebunden;
  relevante ungültige Intervalle bleiben harte Fehler.
- Ein belegter Konfigurations-, Producer- oder Generationswiderspruch in einer
  gebundenen Konfigurationsaufnahme veröffentlicht eine negative Bereichsmaske
  über die vollständig vergangenen UTC-Stunden der Bindung. Dadurch bleiben
  alte disjunkte positive Captures außerhalb des aktuellen Abfragefensters
  nicht unbemerkt freigegeben. Tatsächliche Verfügbarkeit und Validierungszeit
  bleiben maßgeblich. [Qualitätsadapter](../archiv/istwert-qualitaetsadapter.md).
- Ensemblefamilien und die anschließende Biaskorrektur erhalten den
  Unvollständigkeitsstatus sowie produktqualifizierte Ausschlüsse. Die
  dokumentierten Familiengewichte bleiben unabhängig von der Mitgliederzahl.
  Collectorberichte trennen dauerhaften Transfer (`capture_complete`) von
  Mitgliedsvollständigkeit (`ensemble_cohort_complete`); das Standardquorum des
  Replays bleibt `1,0`.
- Der optionale EPS-Replay verlangt eine homogene AC- oder DC-Messgrenze und
  benennt die synchron summierten Stufen. Gemischte Standorte werden vor der
  Mitgliedsrechnung abgelehnt. Ist-/Kalibrierungsbelege müssen dieselbe Summe
  betreffen. `evaluate.py --comparison-archive` verlangt eine ausdrücklich
  gewählte Quellenfamilie über `input.sources`.
- Die synthetische Forecast-CLI reicht auch bei halben/viertel UTC-Offsets bis
  zum lokalen Horizontende. Sie bleibt eine Demo des ersten konfigurierten
  Modells mit Mittelpunktnäherung, kein archivierter Wetterbeleg.

Die Archivtimer für HA, Wetter und den kompatiblen kombinierten Observations-Job
verwenden ausdrücklich UTC. Der tägliche Retentionstermin bleibt lokal. Ein
HACS-Update installiert oder aktiviert keine Hosttimer. Der bereits getrennt
abgenommene Hostwechsel auf den Funktionsstand `f1c7d9b` ist ein eigener Nachweis;
er installiert keine HA-Integration und ersetzt die folgende HACS-Abnahme nicht.

Die vollständige [Befundzuordnung und Korrekturprüfung](../entwicklung/grok-befundkorrekturen-20261103.md)
erläutert auch die widerlegten Behauptungen. Dokumentation zu Messlücken,
Datenflüssen und Versionsständen wurde mit der Implementierung abgeglichen.

## Upgrade von 0.2.21 und Rückweg

Vor dem HACS-Download Komponentenstand, Optionen und Historie sichern.
Bestehende Einträge weiterverwenden; nach dem Download einmal Core neu starten
und die [Erfolgskontrolle](../anwendung/installation.md#5-erfolg-prüfen) durchführen.
Die HA-Abhängigkeitspins bleiben `pvlib==0.16.1` und `scikit-learn==1.9.1`.
Core-/OS-Upgrade, neue Entity-IDs, geänderte Anlagenparameter oder eine
Reinitialisierung der Historie sind für diese Korrekturen nicht erforderlich.

Die folgenden Kompatibilitätsgrenzen sind vor dem Update zu beachten:

- **Legacy-Replay:** Alte Exporte ohne überwachten Gültigkeitsbeginn können
  weiterhin den damaligen Forecast rekonstruieren. Mit konfigurierter
  Messgültigkeitsquelle qualifizieren sie keine ungesperrte Leistung für einen
  vollständigen Schattenneulern-Replay. Bereits gesperrte oder fehlende Leistung
  bleibt lesbar. Fehlende Phasenbelege werden nicht nachträglich erfunden.
- **Snapshots:** Ein Import über der ursprünglichen Cap wird vor dem Speichern
  abgelehnt. Enthält ein vorhandener Store ungültige Pflichtdaten, bleibt seine
  Datei unverändert und schreibgeschützt; die aktive Historie wird daraus nicht
  ungeprüft übernommen. Eine beschädigte optionale Stundenkurve allein wird
  unabhängig von einer gültigen Tagessumme ausgelassen. Nicht direkt `.storage`
  bearbeiten und keine Werte an die Grenze clippen.
- **Neue Producerpins:** Die neuen Integrationsbytes ändern den Producerhash.
  Historische Originale und Pins bleiben an ihre tatsächliche Quelle gebunden.
  Eine vorhandene v2-Quellenperiode vor dem belegten Producerwechsel begrenzen;
  neue Pins ausschließlich für neue, gesondert attestierte Zeiträume verwenden.
  Eine alte Bindung darf nicht ungeprüft über den Wechsel offenbleiben: ein
  Widerspruch kann ihre gesamte vergangene Freigabe widerrufen.
- **Archivhost:** Runtime, Manifest und Timer sind gesondert zu aktualisieren
  und rückzulesen. Die bereits erfolgte Hostabnahme gilt nur für ihren
  eingefrorenen Quell-/Binär-/Runtimeumfang; spätere HACS-Versionsmetadaten
  lösen keinen zusätzlichen Hostwechsel aus.

Für einen Code-Rückweg den gesicherten Komponentenstand oder die vorherige
HACS-Version verwenden und Core neu starten. Eine ältere Version ist keine
automatische Rückmigration neuer Historie. Originalarchive, fortgeschriebene
Checkpoints und gültige Messdaten nicht aus einer alten Sicherung überschreiben;
HA- und Hostrückweg bleiben getrennt.

## Prüfung und Veröffentlichungsgrenzen

Der eingefrorene Korrekturstand vor dem Versionsbump bestand unter Python 3.14
und echtem HA Core 2026.10.4 **3.077 Tests ohne Skips bei 91,45 % kombinierter
Zeilen-/Zweigabdeckung** mit unverändertem 90-%-Gate. Dazu gehören echtes
Setuprollback, Dateipersistenz, Phasenexport und Subprozess-Replay. Zusätzlich
bestanden 42 historische Native-Differential-/Projektionsfälle. Die korrigierten
Familien und der vollständige integrierte Diff wurden unabhängig nachgeprüft.
Diese Nachweise gelten für ihren eingefrorenen Stand; der Releasecommit und
seine Pakete erhalten eine eigene Prüfung.

Tests, gezielte Nachreviews und die historische Grok-Befundprüfung sind kein
neuer akzeptierter externer Gesamtquellreview. Sie belegen weder physische
Quellenqualität, produktive Lernfreigabe noch bessere Prognosen.

## Veröffentlichungs- und Installationsstatus

Die Metadaten und Dokumentation für 0.2.22 sind vorbereitet. Releasecommit,
Versionstag, Build-/Downloadhashes, CI-Verweise und die tatsächliche
HACS-/HA-Erhaltungsprüfung werden erst nach ihren jeweiligen erfolgreichen
Schritten dokumentiert. Bis dahin ist keine Installation dieser Version
behauptet. Der gesonderte Hoststand `f1c7d9b` ist bereits abgenommen.
