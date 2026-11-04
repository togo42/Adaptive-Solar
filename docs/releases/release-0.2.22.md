# Adaptive Solar 0.2.22

Stand: 04.11.2026, **veröffentlicht und über HACS installiert** als
[v0.2.22](https://github.com/togo42/Adaptive-Solar/releases/tag/v0.2.22) auf
[Releasecommit `67a4337`](https://github.com/togo42/Adaptive-Solar/commit/67a4337dfadadc8e65168d164174acb13eb6c3f6).
Der korrigierte Funktionsstand ist `f1c7d9b2417cbad934ea082907c0ff7a498d1e20`.
Die begrenzte Adaptive-Solar-Erhaltungsprüfung ist abgeschlossen. Das
Gesamtsystem bleibt wegen zweier offener Neustartmeldungen anderer Integrationen
nicht vollständig repairfrei.

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
  Eine vorhandene v2-Quellenperiode vor dem ersten Datei-/Neustartwechsel am
  tatsächlichen UTC-Zeitpunkt halb offen begrenzen; nicht auf die nächste
  Stunde runden. Bestehende Pins, Konfigurationsanker und Qualifikationsbelege
  erhalten; neue Pins ausschließlich für neue, gesondert attestierte Zeiträume
  verwenden und keine neue Bindung blind anlegen.
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

Der eingefrorene Korrekturstand und separat auch der Releaseumfang bestanden unter Python 3.14
und echtem HA Core 2026.10.4 **3.077 Tests ohne Skips bei 91,45 % kombinierter
Zeilen-/Zweigabdeckung** mit unverändertem 90-%-Gate. Dazu gehören echtes
Setuprollback, Dateipersistenz, Phasenexport und Subprozess-Replay. Zusätzlich
bestanden 42 historische Native-Differential-/Projektionsfälle. Die korrigierten
Familien und der vollständige integrierte Diff wurden unabhängig nachgeprüft.
Diese Nachweise gelten für ihren eingefrorenen Stand. Die CI-Läufe des exakten
Releasecommits sind für [main](https://github.com/togo42/Adaptive-Solar/actions/runs/41813610157),
[Arbeitsbranch](https://github.com/togo42/Adaptive-Solar/actions/runs/41813610088)
und [Versionstag](https://github.com/togo42/Adaptive-Solar/actions/runs/41813610171)
erfolgreich. Wheel und sdist wurden isoliert gebaut; das Wheel wurde frisch
installiert und alle 35 Pythonmodule der Integration daraus importiert. Die
Paketbytes wurden gegen die Releasequellen geprüft.

Tests, gezielte Nachreviews und die historische Grok-Befundprüfung sind kein
neuer akzeptierter externer Gesamtquellreview. Sie belegen weder physische
Quellenqualität, produktive Lernfreigabe noch bessere Prognosen.

## Veröffentlichungs- und Installationsstatus

Der Versionstag `v0.2.22` zeigt unverändert auf Releasecommit
`67a4337dfadadc8e65168d164174acb13eb6c3f6`. Alle vier öffentlichen Releaseassets
wurden heruntergeladen und bytegleich mit den lokal geprüften Paketen verglichen:

| Releaseasset | SHA-256 |
| --- | --- |
| [HACS-ZIP](https://github.com/togo42/Adaptive-Solar/releases/download/v0.2.22/adaptive_solar.zip) | `60cf354dee7e41804349c78d849fd5fea4413b90963c8c82fc484e2e24f4b501` |
| [Wheel](https://github.com/togo42/Adaptive-Solar/releases/download/v0.2.22/adaptive_solar_ha-0.2.22-py3-none-any.whl) | `f0846958c8451eace7678845d7524edef4b31959c31d127774e27de7c089749e` |
| [sdist](https://github.com/togo42/Adaptive-Solar/releases/download/v0.2.22/adaptive_solar_ha-0.2.22.tar.gz) | `47e5928687f15c3d728bc583c742f066ce6a58ccfd3b32886f417abab0ebe819` |
| [Prüfsummen](https://github.com/togo42/Adaptive-Solar/releases/download/v0.2.22/SHA256SUMS) | `405c2dc872e4d41d8eb312d11155daedd654d523c3b0166bd810940d271cac26` |

Die native HACS-Installation erfolgte nach geprüfter Sicherung mit genau einem
Core-Neustart unter unverändertem **Core 2026.10.4**. Alle 42 installierten
Komponentendateien entsprechen exakt dem Releasecommit. Bestehende Einträge,
Optionen, Entity-/Unique-IDs, Geräteidentitäten sowie Energy-/Dashboardbezüge
blieben erhalten. Ebenso unverändert sind die abgegrenzten abgeschlossenen
Messintervalle, früheren Tagesstartwerte einschließlich Kurven/Provenienz und
die abgeglichenen Comparisonoriginale. Ein Daten- oder Komponentenrestore wurde
nicht ausgeführt.

Dies bedeutet keine Bytegleichheit kompletter Historienstores: Begrenzte
Forecastrepräsentanten werden unter der laufenden Auswahl ersetzt. Ihre
Cacheerhaltung ist von der Erhaltung echter Messintervalle und eingefrorener
Tagesstartwerte zu unterscheiden.

Nach echten neuen Eingangsdaten bestätigte die begrenzte Produktprüfung gültige
konfigurierte Eingänge, vollständige Folgetage und vier neue Originalexporte
mit Version 0.2.22 und dem tatsächlichen Producerquellhash. Die Konfiguration
ist gültig; die geprüften Adaptive-Solar-Laufzeit-/Startlogs sind unauffällig.
Der frühere negative Startupreadback bleibt als eigener Nachweis erhalten.
Die anschließende Prüfung aller Adaptive-Solar-Produktgates ist erfolgreich.

**Gesamtsystemgrenze:** Zwei offene HACS-Neustartmeldungen betreffen andere
Integrationen. HA ist daher nicht vollständig repairfrei; die ursprüngliche
globale Abnahme bleibt negativ. Die getrennte Adaptive-Solar-Produktabnahme
bestätigt ausschließlich die beschriebenen Erhaltungs-/Runtime-/Exportgates.
Aus den Meldungen wird kein Verursacher abgeleitet. Ein zweiter Core-Neustart
oder Änderungen an diesen anderen Integrationen gehören nicht zu dieser Abnahme.

Die alten externen Quellenperioden wurden vor Releasepublication und
HACS-Download am realen UTC-Cutover geschlossen. Alte Originale und Pins bleiben
erhalten; neue prospektive Bindings wurden nicht blind angelegt. Fehlende ganze
Stundenunterstützung nach dem Wechsel bleibt fehlender Nachweis. Der gesonderte
Hoststand `f1c7d9b` bleibt unverändert; die vorübergehend pausierten Timer wurden
nach der begrenzten Produktabnahme mit ihren ursprünglichen Zuständen
wiederhergestellt. Installation und Erhaltungsprüfung
qualifizieren keine physische Quelle und belegen keine bessere Prognose.
