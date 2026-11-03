# Performanceanalyse und Rust: Übergabe für die nächste Sitzung

Stand: 02.11.2026. Geprüfte Quellbasis:
`83ea45b1198451a22767aab6f633382209340f27`, Branch
`codex/learning-support-guard`. Die Befunde beziehen sich auf diesen Checkout;
installierte HA- und Archivhoststände wurden dafür nicht geprüft.

Fortsetzung am 02.11.2026:
[lokale Bestandsaufnahme und Laufzeitmessung](performance-bestandsaufnahme.md).
Die folgenden Befunde bleiben an die oben genannte Ausgangsbasis gebunden.

Fortsetzung am 03.11.2026: Die [Originalvalidierung](performance-originalvalidierung.md)
vermeidet redundante Baumdurchläufe. Ein [lokaler Auswahlprototyp](performance-archivauswahl.md)
trennt vollständigen Kaltaufbau und gebundene Wiederverwendung;
die [Rustbewertung](performance-rust.md) beschreibt den möglichen Hostumfang
und den noch fehlenden Rust-Laufzeitnachweis. Diese Entwicklungsschritte sind
keine produktive Aktivierung.

## 1 Auftrag und Aussagegrenzen

Ausgangspunkt ist die vom Nutzer als sehr langsam beschriebene Hostprobe auf
dem externen Archivhost und die Frage, ob einzelne Softwareteile von Rust
profitieren könnten. Anschließend wurde die Codeprüfung auf weitere mögliche
Überarbeitungen ausgeweitet. Dieser Auftrag hält die Erkenntnisse für eine
spätere Sitzung fest; er setzt noch keine Optimierung um.

Die genaue auf dem Host ausgeführte Probe, ihre Argumente, Datenmenge und
Laufzeiten sind noch zu bestimmen. Der untersuchte Archiv-/Qualitätspfad ist
ein möglicher Bezugspunkt, keine bestätigte Zuordnung des langsamen Prozesses.
Es gibt aus dieser Untersuchung kein Hostprofil und keine gemessene
Beschleunigung. Bestätigte Codestrukturen, vermutete Kosten und vorgeschlagene
Änderungen bleiben deshalb getrennt.

Empfehlung: zuerst vollständig messen, dann unnötige Arbeit und Datenzugriffe
reduzieren. Rust erst für einen danach nachgewiesenen Rechenengpass bewerten.
Eine schnellere Verarbeitung belegt keine höhere Prognosegüte.

## 2 Befunde aus dem aktuellen Code

### 2.1 Archivselektion und Qualitätsprüfung

**Bestätigt:** [continuous_quality.derive](../../scripts/continuous_quality.py)
ruft je gebundener Quelle `ArchiveStore.iter_events(source=...)` auf und filtert
danach Ereignisarten, Empfangszeiten und relevante Intervalle beziehungsweise
Konfigurationsaufnahmen. [ArchiveStore.iter_events](../../custom_components/adaptive_solar/core/archive.py)
liest dabei alle indexierten Originalbatches der Quelle; die komprimierten
Originale werden gelesen und geprüft. Der Zeitraumfilter wird nicht als
gezielte Batchauswahl an den Store übergeben.

In [actual_quality._hour](../../custom_components/adaptive_solar/core/actual_quality.py)
wird für jede Zielstunde die vorbereitete Intervallliste erneut nach
Überlappungen durchsucht. Vorbereitung und Konfigurationsprüfung durchlaufen
Ereignisse außerdem pro Bindung. Ausgewählte Ereignisse werden mehrfach für
Budgetprüfung, Validierung oder Hashbildung serialisiert.

**Mögliche Wirkung:** Mit wachsendem Archiv können gelesene und verarbeitete
Daten weit über dem eigentlichen Zielzeitraum liegen. Dateizugriffe,
Dekompression, JSON-Verarbeitung und Intervallsuchen sind getrennt zu messen.

**Prüfauftrag:** Benötigte Batches gezielt auswählen und Stunden chronologisch
zuordnen. Anker, Payloadabhängigkeiten, Konfigurationsänderungen und
Widersprüche aus anderen Generationen müssen weiterhin vollständig erfasst
werden. Der SQLite-Index bleibt ableitbar; seine Nutzung ersetzt keine
Originalprüfung. Verträge und Auswahlbudgets stehen im
[Istwert-Qualitätsadapter](../archiv/istwert-qualitaetsadapter.md).

### 2.2 Gesamtlaufzeit und Prognoseexport

**Bestätigt:** Im [Coordinator](../../custom_components/adaptive_solar/coordinator.py)
messen `join_seconds`, `fit_seconds` und `forecast_seconds` einzelne Phasen.
`forecast_seconds` endet unmittelbar nach der Hauptprognose. Anschließend
folgen Bias-Shadow-Fit/-Vorhersagen und bei aktiviertem Export vollständige
Physikprognosen für jedes Wettermodell über weitere `engine.forecast`-Aufrufe.
Auch Exportaufbereitung und Serialisierung liegen außerhalb dieser
Prognosezeit. Vor dem Worker werden Historien kopiert.

**Mögliche Wirkung:** Die vorhandenen Teilzeiten erklären nicht die gesamte
Aktualisierungsdauer. Zusätzliche Einzelmodellprognosen können wiederholte
Physikarbeit verursachen.

**Prüfauftrag:** Gesamtlauf und alle wesentlichen Phasen messen. Gemeinsame
Physikzwischenergebnisse wiederverwenden, soweit die Eingaben identisch sind.
Die Einzelmodellarme verwenden keine Beobachtungen und keinen Lerner; ihre
Semantik unterscheidet sich von der Hauptprognose. Sie dürfen nicht einfach
durch deren korrigierte Ergebnisse ersetzt oder als vermeintlich entbehrlich
entfernt werden.

### 2.3 Trainingsjoin und Fit-Wiederverwendung

**Bestätigt:** `join_training()` bereitet Messintervalle erneut auf, sortiert
sie und baut Messindizes. Der Aufruf liegt vor dem Vergleich der Fit-Signatur.
Eine Wiederverwendung des vorhandenen Lerners spart daher nicht den Join.
Die Signatur berücksichtigt unter anderem Historienrevision, lokalen Tag,
serialisierte Schattentabelle, tatsächliche Samples und Alignmentdiagnose.

**Prüfauftrag:** Stabile Messindizes und abgeschlossene Zielauswertungen gezielt
wiederverwenden; Invalidierung und Speicherbudget vorher festlegen. Ein Cache
darf nicht nur Zeilenzahlen oder Historienrevisionen vergleichen. Auch ohne
neue Zeilen können Ziele abgeschlossen oder Labels am neuen `as_of` erstmals
verfügbar werden. Änderungen an Messwerten, Origins, Retention und
Verschattungszustand müssen berücksichtigt werden.

Ein fester Refitabstand ist eine eigene Verhaltensänderung: Er kann den
Aktivierungszeitpunkt oder die verwendeten Prognosen verändern. Zunächst
verhaltensgleiche Wiederverwendung untersuchen. Die ältere Planung
[AS-OPT-02/04](../recherche/adaptive-solar-bewertung.md) ist als Hintergrund
nützlich, bleibt aber an ihre historische Quellbasis gebunden.

### 2.4 Gebündelte Physik- und ML-Aufrufe

**Bestätigt:** [physics._position](../../custom_components/adaptive_solar/core/physics.py)
ruft pvlib für einen einzelnen Zeitpunkt auf. Sonnenstand und mehrere
Clear-Sky-Funktionen besitzen bereits begrenzte LRU-Caches; die
Clear-Sky-Komponentenmittel bündeln bereits acht Quadraturzeitpunkte.
Eine pauschale Empfehlung, erst Caches einzubauen, wäre deshalb unzutreffend.

[ResidualLearner.predict](../../custom_components/adaptive_solar/core/learning.py)
ruft das Modell mit jeweils einem Featurevektor auf. Im Prognosepfad geschieht
dies innerhalb der Verarbeitung einzelner Zielintervalle und Ausgangsstufen.

**Prüfauftrag:** Bei relevantem Aufwand neue Sonnenstandszeitpunkte gemeinsam
berechnen und ML-Vorhersagen nach Modell/Regime bündeln. Alle bisherigen
Prüfungen je Zeile, Statuswerte, Ausgabereihenfolge, Grenzen und Fallbacks
erhalten. Kalte und warme Caches sowie aktives ML getrennt messen.

### 2.5 HA-Ereignisloop, Historie und Modulstruktur

**Bestätigt:** Der Coordinator kopiert `archive` und `intervals` mit `deepcopy`
vor dem Worker. `_prune()` filtert Historien und baut den Index der zuletzt
gespeicherten Intervalle erneut auf. Es wird bei Aktualisierungen und beim
Aufbau des zu speichernden Zustands aufgerufen.

Der Coordinator vereint Messwerterfassung, Training, Prognose, Schattenmodelle,
Export und Persistenz. Das Vergleichsarchiv besitzt bereits revisionsgebundene
Speicherung, Workeraufbereitung und Hash-Readback; diese Schutzmechanismen
müssen bei einer Überarbeitung erhalten bleiben.

**Prüfauftrag:** Kopierdauer und Ereignisloop-Latenz bei großer Historie messen.
Unveränderliche Datensichten, gezielte Kopien und inkrementelle Pflege prüfen.
Keine veränderlichen Ereignisloop-Daten ungeschützt an Worker weitergeben.
Messhistorie, Trainingsaufbereitung und Export in klarere Verantwortlichkeiten
aufzuteilen wäre ein Wartbarkeitsziel; allein die Aufteilung verspricht keine
Beschleunigung.

### 2.6 Weitere nachrangige Messpunkte

[archive_host.run](../../scripts/archive_host.py) serialisiert Timerjobs über
einen gemeinsamen Writerlock. Vor jedem geplanten Unterbefehl berechnet
`capacity()` den belegten Archivplatz über einen Verzeichnisdurchlauf mit
Dateimetadatenzugriffen. Wartezeit auf den Lock und Kapazitätsprüfung separat
messen; langsame Gesamtzeit bedeutet nicht zwingend langsame Berechnung.
Schreibschutz und Kapazitätsgrenzen bleiben bestehen.

[OpenMeteoClient](../../custom_components/adaptive_solar/weather.py) hat bereits
einen Cache pro Konfigurationseintrag und ruft Wettermodelle parallel ab.
Bei identischen Anfragen mehrerer Einträge wäre gemeinsame Abrufnutzung ein
späterer Prüfpunkt. Cachealter, Originalantworten und Empfangsprovenienz müssen
dabei erhalten bleiben. Ein Bedarf wurde hier nicht gemessen.

## 3 Prioritäten und Rust-Entscheidung

| Reihenfolge | Arbeitspaket | Abschlusskriterium |
| --- | --- | --- |
| 1 | Langsamen Hostprozess identifizieren und vollständiges Profil erstellen | Reproduzierbare Zuordnung von Laufzeit, Datenvolumen und Phasen |
| 2 | Archivselektion und Intervallzuordnung untersuchen | Gleiche Evidenz und Entscheidungen bei gemessen geringerem Aufwand |
| 3 | Trainingsjoin und Exportarbeit untersuchen | Nachgewiesene Wiederverwendung ohne veraltete oder anders definierte Ergebnisse |
| 4 | Physik-/ML-Aufrufe und HA-Historienpflege untersuchen | Nutzen bei relevanten Historiengrößen und vertretbarem Speicherbedarf |
| 5 | Modulstruktur verbessern | Klarere Zuständigkeiten und erhaltenes Verhalten |
| 6 | Verbleibenden Rechenkern für Rust bewerten | End-to-End-Vorteil einschließlich Übergabe-, Build- und Wartungsaufwand |

Rust ist ein möglicher Kandidat für klar begrenzte, häufig ausgeführte
Intervall- oder Validierungsberechnungen, wenn diese nach den vorherigen
Schritten noch erheblich zur Laufzeit beitragen. Eine Python-Erweiterung über
PyO3 oder ein eigenständiger Hosthelfer wären mögliche Integrationsformen;
eine Auswahl wurde nicht getroffen.

Ein Sprachwechsel beseitigt weder unnötige Vollscans noch Wartezeiten auf
Netzwerk oder Sperren. Zunächst bleibt die bestehende Pythonimplementierung
Referenz. Eine vollständige Portierung der HA-Integration oder der
Physik-/ML-Bibliotheken ist aus dieser Prüfung nicht begründet. Ein möglicher
Hostbaustein sollte keine neue Pflichtabhängigkeit für HA erzeugen.

## 4 Messung und Abnahme

Vor dem ersten Versuch festhalten: Quellcommit, Interpreter und Abhängigkeiten,
Hardware, tatsächlichen Befehl und Eingabehashes, Archivgröße/Batchzahl,
Zeilen-/Bindungszahlen, Zielzeitraum, Cachezustand und aktiven Lernzustand.
Private Hostdetails und Eingaben bleiben außerhalb der öffentlichen Dokumente.

Für dieselbe eingefrorene Eingabe Referenz und Kandidat vergleichen. Nach
Möglichkeit mehrere Wiederholungen mit Median, p95 und Wiederholungszahl
berichten; bei wenigen Läufen keine belastbare p95-Aussage ableiten. Erfassen:

- Gesamtdauer und CPU-Zeit, Spitzen-RAM und gegebenenfalls Ereignisloop-Latenz.
- Lockwartezeit, Kapazitätsprüfung, Netzwerkzeit und gelesene Batches/Bytes.
- Dekompression, Parsing, Originalprüfung, Auswahl und Payloadauflösung.
- Trainingsjoin, echte Fits/Wiederverwendungen, Physik/Nowcast, Schattenmodell,
  Exportaufbereitung, Serialisierung und Persistenz.

Für die Python-3.14-Entwicklungsumgebung kommt `cProfile` für synchrone
Teilberechnungen infrage. In separaten Prozessen oder Workerthreads ausgeführte
Arbeit gesondert instrumentieren; ein Profil nur des Wrappers erklärt nicht
automatisch dessen Kinder. Uninstrumentierte Vergleichsläufe ergänzen die
Messung, weil Profiling eigenen Aufwand verursacht.

Die Abnahme schützt Originalbytes, Quellen-/Generations-/Konfigurations- und
Producerpins, kanonische Hashes, Einheiten, Lücken, Gates und tatsächliche
Verfügbarkeit. `as_of` und `validated_at` bleiben getrennt; im echten Lauf wird
keine Abschlusszeit zurückdatiert. Für verhaltensgleiche Tests kontrollierte
Uhren verwenden. Neue reale Ableitungen dürfen wegen neuer Abschlusszeiten
andere Metadatenhashes haben; deren Bedeutung ist getrennt von der Gleichheit
der fachlichen Entscheidungen zu prüfen.

Numerische Toleranzen gelten ausschließlich nach dem bestehenden
[Replayvertrag](../archiv/archivbetrieb.md), nicht pauschal für Rohdaten,
Strukturen oder Entscheidungen. Regressionen müssen insbesondere fehlende und
widersprüchliche Evidenz, nachträgliche Labelverfügbarkeit, Retention und beide
DST-Wechsel abdecken. Rust müsste zusätzlich die bestehende JSON-/Hashsemantik
und das Verhalten an Grenzfällen nachweisen. Passende Verhaltenstests und
Dokuabgleich gehören zu jeder späteren Implementierungsänderung.

## 5 Einstieg in die nächste Sitzung

1. Dieses Dokument, Repository-AGENTS und aktuellen Gitstatus lesen; die
   gemeinsame Projektsuche unter `prognosemodelle` ausführen.
2. Aktuellen Checkout mit der oben genannten Basis vergleichen. Lokalen Code,
   installierten HA-Stand und Hoststand getrennt behandeln.
3. Den tatsächlich langsamen Probenbefehl anhand vorhandener privater
   Betriebsbelege beziehungsweise lesender Hostdiagnose identifizieren. Erst
   dann entscheiden, welche der beschriebenen Pfade betroffen sind.
4. Mit einem begrenzten lokalen Messaufbau auf geeigneten eingefrorenen
   Eingaben beginnen. Ergebnisse und Grenzen dokumentieren, danach einen
   einzelnen nachgewiesenen Engpass auswählen.
5. Erst nach dem Kostenbefund eine verhaltensgleiche Optimierung umsetzen und
   testen; Rust anhand des verbleibenden Aufwands entscheiden.

Dieser Dokumentationsauftrag autorisiert keine produktiven HA-/Hoständerungen,
Timerumstellung, Installation, Neustarts oder externe Datenübertragung. Ein
lastintensiver Probelauf auf dem Produktivhost ist ein gesonderter Schritt.

Möglicher Startauftrag für die neue Sitzung:

```text
Lies docs/entwicklung/performance-uebergabe.md und prüfe den aktuellen Stand.
Beginne mit der Zuordnung der langsamen Hostprobe und einem begrenzten lokalen
Messaufbau. Nutze die Messung, um den ersten Optimierungsschritt zu bestimmen.
Produktive HA-/Hoständerungen und eine Rust-Portierung zunächst zurückstellen.
```

## 6 Geprüfte externe Grundlagen

Links geprüft am 02.11.2026. Die Quellen stützen Werkzeugmöglichkeiten;
sie belegen keinen Geschwindigkeitsgewinn für dieses Projekt.

- [Python-3.14-Profiling](https://docs.python.org/3.14/library/profile.html):
  `cProfile` und Auswertung von Aufrufen und Laufzeiten.
- [scikit-learn: Computational Performance](https://scikit-learn.org/stable/computing/computational_performance.html):
  gebündelte gegenüber einzelnen Vorhersagen.
- [pvlib: get_solarposition](https://pvlib-python.readthedocs.io/en/stable/reference/generated/pvlib.solarposition.get_solarposition.html):
  Berechnung für einen `DatetimeIndex`.
- [PyO3](https://github.com/PyO3/pyo3): Rust-Erweiterungen für Python.
