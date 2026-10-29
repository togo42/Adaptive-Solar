# Historische Prüfstände und Nachweisgrenzen

Stand der Zusammenfassung: 29.10.2026. Diese Angaben wurden aus den bisherigen
versionierten Release- und Prüfberichten übernommen. Sie beschreiben damalige
Prüfungen; die Dokumentationsneuordnung ist weder ein neuer vollständiger
Integrationsreview noch eine erneute Laufzeitprüfung.

## Aktueller Releasebezug

[0.2.18](../releases/release-0.2.18.md) wurde aus
`9059bc3b69ec6f123c4293babb419b56afb2cfff` veröffentlicht. Die damalige
Main-/Tag-CI bestand mit jeweils **1.727 Tests ohne Skips**, mindestens
**90,85 % kombinierter Abdeckung** und erfolgreichen HA-freien Archivhostjobs.
Vier veröffentlichte Releaseartefakte wurden nach Download bytegleich geprüft.
Die vollständige Suite verwendete Python 3.14 und HA Core 2026.10.4 mit
Testplugin 0.13.375. Frühere Prüfungen unter Core .2/.3 qualifizieren diese
Plattformen nicht erneut für 0.2.18.

Der vollständige Codex-Review (`gpt-6.1-sol`, Effort `high`) akzeptierte den
Quellstand `70966fcda17d92ada852e77097a3707d226b5db2` ohne Findings:
Payload-SHA256 `572529575cf2fb199e97617a67dab96a6f13beafd5cf0e23ab6ec2977aa312c1`,
42 Quellchunks und ein Abschlussturn, keine native Kontextkürzung oder Tools.
Releaseversionsnummern und spätere Dokumentation sind davon getrennte Änderungen.
Der heutige Dateibaum übernimmt diesen Reviewstatus nicht automatisch.

## Offline-Support-Guard im Entwicklungsstand

Lokale Prüfung vom 29.10.2026, ausgehend von `dac9b8e1`, für den separaten
[Support-Guard-Kandidaten](../technik/learning-support-guard.md).
Komponenten-Quellhash:
`07c78d5883686e251fcc8b9e66b11682ca2500c72d4ed443553de821e71f3728`.
Die vollständige Suite bestand mit **1.784 Tests, null Fehlern und null Skips**;
kombinierte Statement-/Branch-Coverage **90,82 %**, Statement-Coverage 93,26 %,
Branch-Coverage 84,99 %. Ruff, `pip check` und die lokale CLI-Importprüfung mit
gesperrten HA-Imports bestanden ebenfalls. Der neue CI-Importaufruf für die
HA-freie Archivhostumgebung ist konfiguriert, aber damit noch kein neuer
erfolgreicher GitHub-CI-Lauf. Die lokale Suite meldete 23 ResourceWarnings zu
nicht geschlossenen SQLite-Verbindungen; es gab keinen Testabbruch.

Ein unabhängiger Subagent prüfte den geänderten öffentlichen Umfang und
reproduzierte eine Quellenvermischung beim Import gleicher Standortkonfigurationen.
Die Korrektur bindet zusätzlich die Archivquelle beziehungsweise bei unbekannter
Quelle die Originalgeneration. Der Nachtest weist unterschiedliche Quellen
zurück. Im geprüften Umfang blieben keine offenen blockierenden Befunde.
Dieser begrenzte Subagent-Review ist kein vollständiger externer Providerreview.

Die Nachweise betreffen Trainingsabdeckung, Zeit-/Quellenbindung, Fallback,
Auswertung und Datenlücken. Sie belegen weder bessere reale Prognosen noch eine
produktive Aktivierung oder die Kalibrierung der festgelegten Supportschwellen.
Es erfolgte kein Release oder HA-Deployment dieses Kandidaten.

## Offline-Qualitätsadapter im Entwicklungsstand

Lokale Prüfung vom 29.10.2026, ausgehend von `a1e3fb8`, für den
[Adapter für Recorder-Iststunden](../archiv/istwert-qualitaetsadapter.md).
Quellhash von `core/actual_quality.py`:
`9109ac44d3f00b687c9a0fb685ab693f90e7b86b6d9fd9433eb8e47b0e79327c`.
Die vollständige Suite bestand mit **1.856 Tests, null Fehlern und null Skips**;
kombinierte Coverage **90,68 %**, Statement-Coverage 93,16 % und Branch-Coverage
84,83 %. Ruff, `pip check` und der CLI-Smoke mit ausdrücklich gesperrten
HA-Imports bestanden. Der zusätzliche HA-freie CI-Aufruf ist konfiguriert;
ein neuer GitHub-CI-Lauf wurde in diesem Auftrag nicht ausgeführt. Die lokale
Suite meldete 23 ResourceWarnings zu ungeschlossenen SQLite-Verbindungen.

Ein unabhängiger Subagent prüfte Core, neue Verhaltenstests und die bestehenden
Producer-/Qualitätsverträge. Korrigiert wurden insbesondere Quellen-/Generations-
widersprüche, unbekannte Intervallfelder, Ankerzeitordnung, widersprüchliche
Abregelungsbindung und explizite negative Qualitätsrevisionen. Die reale
Offlineauswertung deckte zusätzlich Rundung bei der Addition kurzer Intervalle
auf: Zwei neue Regressionen scheiterten zuvor; exakte Zeitdauern erhalten nun
volle Abdeckung und schließen zugleich eine echte Mikrosekundenlücke aus.
Der Nachreview dieses Fixes ist abgeschlossen; keine offenen konkreten Befunde
im geprüften Coreumfang. Dies ist kein vollständiger externer Providerreview.

Die Nachweise betreffen Ableitung, Originalerhalt, Revisionen und nachvollziehbare
Ausschlüsse. Sie ersetzen keine Quellenattestierung oder Prognosegütemessung.
Es erfolgten kein Release, keine Timeranbindung und keine produktive Aktivierung.

## Entwicklungskandidat: fortlaufende Quellenbindung und Qualitätsaufnahme

Stand 29.10.2026, aufbauend auf dem Offlineadapter. Native Originaldeltas tragen
nun Konfigurations-/Producerpins und die Energie-Entity. Eine begrenzte v2-Policy
ermöglicht die erneute Qualitätsableitung bei jeder Recorder-Aufnahme; die
Hostoption ist vorbereitet und ausdrücklich optiert. Vertrag, Vorlage,
Abnahmeschritte und Rücknahme stehen im
[Qualitätsadapter-Leitfaden](../archiv/istwert-qualitaetsadapter.md#5-fortlaufende-quellenbindung-und-qualitätsaufnahme).

Die finale lokale Suite bestand mit **1.875 Tests ohne Skips** und
**90,72 % kombinierter Zeilen-/Branchabdeckung**, unverändertes 90-%-Gate.
138 gezielte Tests prüfen insbesondere Originalerhalt, bedingte Quellenpins,
Konfigurations-/Producerabweichungen, alte Intervalle ohne Pins, begrenzte
Freigabezeiträume, beide Zeitumstellungen, Payload-Chunks, getrennte
Qualitätsverfügbarkeit, Aufnahmefehler und Berichtgrößenlimits. Native HA-Tests
prüfen die zusätzlichen Exportfelder bei unveränderten internen Lernintervallen
sowie fortgesetzte Forecastausgabe bei fehlgeschlagener Provenienzlesung.
Die Suite meldete weiterhin 23 ResourceWarnings zu ungeschlossenen
SQLite-Verbindungen; diese sind kein Stabilitätsnachweis für einen Livebetrieb.

Ruff, `pip check`, CLI-Smokes mit ausdrücklich gesperrten HA-Imports und
Dokumentationslinks/Markdownvorschauen wurden geprüft. Ein lokaler synthetischer
Archiv-Probelauf qualifizierte zwei Stunden bei unverändertem Recorder-Rohstand;
Eingaben, Ausgabe und Implementierungshashes liegen ignoriert unter
`artifacts/continuous-quality/rehearsal/`, die finale Testausgabe und Coverage
unter `artifacts/continuous-quality/`. Diese lokalen Artefakte sind keine
öffentlichen Downloads und enthalten keinen produktiven Quellenqualitätsnachweis.

Ein aktiver lokaler Self-Review prüfte insbesondere Fehlerpfade, die Bewahrung
der Rohaufnahme bei fehlgeschlagener oder zu großer Qualitätsableitung und die
Abgrenzung historischer v1-Attestierungen von bedingten v2-Policies. Ein
vollständiger externer Providerreview, neue GitHub-CI, Release sowie HA-/Host-
Installation und Timeraktivierung wurden in diesem Auftrag nicht ausgeführt.
Der reale Probelauf benötigt separat qualifizierte Quellen und Originaldeltas
des neuen Producers; Laufzeit und Ankererhalt sind am tatsächlichen Archiv zu prüfen.

## Codex-Abnahme: erster Lauf und Befundkorrekturen

Der Vollreview von `f2c41ece343ed52198ba743aab7f71afab741e81` durch
**Codex GPT-6.1-Sol/high**, CLI 0.165.0, endete am 29.10.2026 mit zwei mittleren
Befunden und Urteil `blocked`. Alle 209 öffentlichen Originaltexte einschließlich
acht systemd-Vorlagen wurden vollständig in 43 Blöcken übertragen. Ein
zusätzlicher Initialisierungsturn und der Abschlussturn ergeben 45 vollständig
abgeschlossene Turns. Der unabhängige Nachweisaudit bestand: exakte Quellen-/
Prompt-/Antwortbytes, native Identität, keine Compaction oder nativen Tools,
vollständiger API-Guard und unveränderter geprüfter Quellstand. Ein gültiger
Review mit Befunden ist keine positive Abnahme.

- AS-001: Der native Supportimport verlor vollständig leere Ausgaben und fehlende
  Stufen. Das neue Versuchsverzeichnis bewahrt jede konfigurierte Stufe je
  Ausgabe-/Empfangsstand. Die jüngste verfügbare Ausgabe wird vor der
  Zielabdeckungsprüfung gewählt; Gesamtkennzahlen, Strata und Banddiagnose
  verwenden denselben Stand. Frühere Cutoffs dürfen frühere Erfolge weiterhin
  sehen, spätere Ausfälle werden nicht durch diese verdeckt.
- AS-002: Das Ausgabeziel des lokalen Qualitätshelfers konnte seine eigenen
  Programmdateien überschreiben. Helfer und verwendete Implementierungsdateien
  sind nun in beiden Pfadprüfungen geschützte Eingaben; Regressionen prüfen
  gleiche Pfade, Symlink-/Hardlink-Aliase sowie einen nach der Ableitung
  entstandenen Alias.

Der geprüfte Payload hat SHA256
`09c63e24372e33ee0603ea294919d72baadf0d58505ecee523254f1692f460e1`,
das erste Receipt SHA256
`006dca7620b01804674cff0f26f27c686d606979d55edd58d11520f8a6ae851e`.
Die Rohbelege liegen lokal unter `reviews/private/continuous-quality-codex-r1/`,
der unabhängige Audit unter `artifacts/continuous-quality/codex-closeout.json`.
Sie sind keine öffentlichen Downloads. Für die aktuelle CLI wurde der isolierte
Reviewtreiber aus Toolingcommit `4ba01bb` verwendet; seine Originalbytes wurden
per Git geprüft und separat gehasht. Nur Zielrepository, die zusätzlichen
Endungen `.service`/`.timer` und das im Kandidaten festgelegte Kontextbudget
800.000 wurden gebunden; sein Dateiscope wurde vor Start exakt mit dem
Kandidatenhelfer abgeglichen. Keine globale CLI-Konfiguration wurde verändert.

Beide Befunde wurden an isolierten Kopien des alten Stands reproduziert:
Bei einem deklarierten jüngeren leeren Versuch zählte der alte Auswerter ein
Erfolgspaar, der korrigierte keines. Der alte Qualitätshelfer ersetzte seine
wegwerfbare Programmkopie durch Ergebnis-JSON und meldete Erfolg. Die neuen
Regressionen lassen weder diese Überschreibung noch ihre Link-Aliase zu.
100 gezielte Tests und die finale Vollsuite mit **1.893 Tests ohne Skips**
bestanden; die kombinierte Abdeckung beträgt **90,74 %** bei unverändertem
90-%-Gate. Weiterhin 23 SQLite-ResourceWarnings. Ruff und der Dokuabgleich
bestanden. Vollsuite und Coverage liegen unter
`artifacts/continuous-quality/review-fixes-full-tests.log` beziehungsweise
`review-fixes-coverage.json`; der lokale Vorher-/Nachher-Beleg liegt unter
`artifacts/continuous-quality/prior-findings-reproduction/`.

Die Korrekturen benötigen einen frischen hashgebundenen Nachreview. Es erfolgten
keine HA-/Hostinstallation, Timeraktivierung oder produktive Modellfreigabe.

## Codex-Nachreview des ersten Korrekturstands

Der vollständige neue Lauf auf `4c5cae0d59190a8ee46baa071a9380adbb2e9a34`
endete am 29.10.2026 erneut mit `blocked`, zwei mittleren Befunden und gültigem
unabhängig nachgeprüftem Kontext-/Transferaudit. Die ursprünglichen Befunde
wurden nicht erneut beanstandet. Scope: 209 öffentliche Originaltexte,
43 Quellblöcke plus Initialisierung und Abschluss, 45 vollständige Turns,
keine Compaction oder nativen Tools. Payload-SHA256:
`fbabd07e7516c31345e18a2cf93a3db3ef38ac14bc7a66891dea9b59663cca72`;
Receipt-SHA256:
`c7f2f472140af40cc1cac03a5845ee5770e3a29429461c15d95bc9e3c1f39e1a`.
Rohbelege: `reviews/private/continuous-quality-codex-r2/`; unabhängiger Audit:
`artifacts/continuous-quality/codex-r2-closeout.json`.

- R2/AS-001: Die Qualitätszeit war vor Beginn der Berechnung erfasst. Der Core
  finalisiert sie nun erst nach Stundenprüfung, Evidenzsortierung und Hashing;
  `qualify_actuals.py` und `continuous_quality.py` übernehmen diese Abschlusszeit.
  Regressionen stellen die Uhr während Abdeckung beziehungsweise Hashing vor:
  ein Cutoff innerhalb der Berechnung erhält keine neuen Labels. Eine rückwärts
  springende Uhr wird zurückgewiesen. Rohdaten und deren Empfang bleiben erhalten.
- R2/AS-002: Der Support-CLI konnte indirekt verwendete Programmmodule
  überschreiben. Die gemeinsame Ausgabeprüfung schützt jetzt alle Pythondateien
  unter `scripts/` und `custom_components/` in sämtlichen nutzenden Berichthelfern.
  Regressionen prüfen direkte Ziele, Symlink-/Hardlink-Aliase und nach der
  Berechnung entstandene Aliase.

Die Befunde wurden auch an isolierten Kopien des R2-Stands reproduziert:
Zwei Labels waren während einer 20 Sekunden dauernden Ableitung bereits nach
15 Sekunden auswählbar; der alte Supporthelfer überschrieb eine wegwerfbare
Modulkopie. Der korrigierte Helfer weist dasselbe Ziel zurück und erhält deren
Bytes. Lokaler Beleg: `artifacts/continuous-quality/r2-findings-reproduction/`.

Die Korrekturen bestanden **204 gezielte Tests** und die finale Vollsuite mit
**1.901 Tests ohne Skips**, **90,74 % kombinierter Abdeckung** und unverändertem
90-%-Gate. Weiterhin 23 SQLite-ResourceWarnings. Ruff, `pip check`, fünf
HA-gesperrte CLI-Smokes und der Dokuabgleich bestanden. Testausgabe/Coverage:
`artifacts/continuous-quality/review-r2-fixes-full-tests.log` und
`review-r2-fixes-coverage.json`.

Auch dieser Nachlauf ist keine positive Abnahme. Der neue Korrekturstand
benötigt einen weiteren frischen hashgebundenen Vollreview. Keine produktive
HA-/Hoständerung oder Aktivierung ist umfasst.

## Weitere Codex-Läufe und gemeinsame CLI-Ausgabesicherheit

Die Läufe R3 und R4 auf `7471284f399f31582ffeef0ec5b8d27fcd08920f`
endeten technisch ohne gültiges Reviewurteil und zählen nicht als Abnahme:
R3 brach im Schlussreview durch einen Sockettimeout ab, R4 bei einem vom Client
vorzeitig geschlossenen nebenläufigen Modellkatalogabruf (`GET /models`,
`BrokenPipeError`). Die API-Guards wiesen beide Läufe zurück; fehlende
Abschlussbelege wurden nicht ersetzt. Lokale Fehlernachweise stehen unter
`artifacts/continuous-quality/codex-r3-failure.json` und `codex-r4-failure.json`.

Ab R4 enthält ausschließlich der isolierte lokale Reviewtreiber eine zusätzliche
I/O-Korrektur: Der Verbindungsaufbau behält seinen kurzen Timeout; danach wird
für Übertragungs-I/O die verbleibende absolute Reviewfrist verwendet und vor
jedem SSE-Leseschritt erneuert. Eine bloße Modellpause beendet den Review dadurch
nicht vorzeitig. Ablauf der Gesamtfrist, native Tools, unbekannte Ereignisse,
unvollständiges EOF und unvollständige Requests bleiben Ablehnungsgründe.
Der ursprüngliche Guard scheiterte am neuen Leerlauf-Regressionsfall, die lokale
Korrektur bestand alle 43 Guardtests einschließlich positiver Pause und negativer
Gesamtdeadline. Originaltreiber, exakter Patch, Code- und Testhashes sind unter
`reviews/private/continuous-quality-codex-driver-r4/` eingefroren. Diese lokale
Transportkorrektur wurde nicht in den öffentlichen Toolingzweig integriert.

R5 prüfte denselben Payload vollständig: SHA256
`92160bbe0ab12899f11078c394231c42357f1e0736e633755b5c8dad3ffb4ea8`,
209 Originaltexte, 44 Quellblöcke plus Initialisierung und Abschluss,
46 vollständig abgeschlossene Turns, keine Compaction oder nativen Tools.
Der unabhängige Audit verifizierte zusätzlich die originale Toolingbasis und den
exakten lokalen Transportpatch. Receipt-SHA256:
`18b3ee94ee60996f4472fbd245b083b1fd5de8d95490ec0b9c362f285d024279`.
Rohbelege: `reviews/private/continuous-quality-codex-r5/`; Audit:
`artifacts/continuous-quality/codex-r5-closeout.json`.

Das Urteil blieb `blocked` wegen eines mittleren Befunds R5/AS-001:
`forecast.py` und `evaluate.py` nutzten den gemeinsamen Programmschutz noch nicht.
Beide CLIs sind nun vor Eingabe-/Netzzugriff und vor Veröffentlichung daran
angebunden; Berichte werden atomar ersetzt. Neue Regressionen prüfen beide CLIs
mit eigenen Skripten und Komponentenmodulen als Ziel, direkten Pfaden,
Symlink-/Hardlink-Aliasen sowie nachträglichen Aliasen. Ein positiver Fall belegt,
dass ein unbeteiligter Hardlink auf den alten Bericht unverändert bleibt.
Im ergänzten Selbstcheck wurden auch neue Berichte in Programmverzeichnissen
und Ausgabe-Aliase auf Manifeste/Ressourcen gesperrt. Berichte werden explizit
als UTF-8 veröffentlicht; ein zusätzlicher Test prüft eine Prozess-Locale ohne
UTF-8. Die finale gezielte CLI-/Ausgabeprüfung bestand mit 87 Tests, die
Vollsuite mit **1.927 Tests ohne Skips** und **90,77 % kombinierter Abdeckung**
bei unverändertem 90-%-Gate. Weiterhin 23 SQLite-ResourceWarnings. Ruff und der
Dokuabgleich bestanden. Finale Testausgabe und Coverage stehen lokal unter
`artifacts/continuous-quality/review-r5-final-full-tests.log` und
`review-r5-final-coverage.json`. Beide Haupt-CLIs wurden am
alten Stand mit wegwerfbaren Programmkopien reproduziert: Alte Fassungen
überschrieben sich mit Ergebnis-JSON, neue wiesen dasselbe Ziel zurück.
Lokaler Beleg: `artifacts/continuous-quality/r5-findings-reproduction/`. Weitere schreibende Helfer wurden auf
äquivalente Schutzgrenzen geprüft: private Pfadgrenzen, neue Ausgabeordner oder
Veröffentlichung ohne Überschreiben bestehender Ziele.

Auch R5 ist keine positive Abnahme; die letzte Korrektur benötigt einen frischen
hashgebundenen Vollreview. Keine produktive Änderung oder Aktivierung ist erfolgt.

## Ältere Quellenprüfungen

| Release | Geprüfter Quellbezug | Historischer Umfang |
| --- | --- | --- |
| [0.2.10](../releases/release-0.2.10.md) | damaliger Implementierungsstand | je 893 Tests ohne Skips unter Core 2026.10.2/.3/.4; Grok 4.7/high ohne Findings |
| [0.2.11](../releases/release-0.2.11.md) | `9070886` | je 900 Tests ohne Skips unter Core .2/.3/.4; Grok 4.7/high, 96 öffentliche Textdateien |
| [0.2.12](../releases/release-0.2.12.md) | `507ab4ecf5af0c205038ca15716f055def00a433` | 978 Tests ohne Skips unter Core .4; Grok 4.7/high, 100 Originaldateien |
| [0.2.13](../releases/release-0.2.13.md) | `9259903` | 1.057 Tests ohne Skips unter Core .4; Grok 4.7/high, 106 Originaldateien |
| [0.2.14](../releases/release-0.2.14.md) | `af3df57` | 1.102 Tests ohne Skips; Grok 4.7/high, 111 Originaldateien |
| [0.2.15](../releases/release-0.2.15.md) | `d1991da6a621c736abbc402bc2ebd7d5a715f707` | 1.364 Tests ohne Skips; 92,57 % kombinierte Abdeckung; Codex GPT-6.1-Sol/high |
| [0.2.16](../releases/release-0.2.16.md) | veröffentlichter Archivzweig | Originalexport, Archiv und Replay; die strengere Originalabnahme wurde erst in 0.2.17 korrigiert |
| [0.2.17](../releases/release-0.2.17.md) | Release `ed901b337da64d41022562ed8a5ba55769cd273a` | Main-/Tag-CI je 1.634 Tests ohne Skips; 90,84 % kombinierte Abdeckung |

Die älteren Releasehinweise erläutern die jeweils korrigierten Fehler und
Upgradegrenzen. Eine vorbereitete oder konfigurierte CI ist kein erfolgreicher
Lauf. Abgebrochene, kompaktierte oder nur teilweise beantwortete Reviewversuche
zählen nicht als abgeschlossener Review. Der [aktuelle Reviewablauf](validierung.md#4-lokale-prüfung-und-review)
verlangt weiterhin vollständige Quellen-, Prompt-, Modell- und Abschlussbelege.

## Öffentliche Aussage und private Evidenz

Tests prüfen Verhalten im erklärten Scope, Coverage die erreichten Codepfade.
Paketbau, nativer HA-Import, installierte Integration, qualifizierter ML-Fit,
Reproduzierbarkeit und tatsächlich bessere Prognosen sind getrennte Nachweise.
Ein begrenzter Laufzeittest auf einer Anlage qualifiziert keine beliebige Hardware.
Ein akzeptierter Originalreplay belegt keine Prognoseüberlegenheit und keine
langfristig ausreichende Archivkapazität.

Konkrete Host-/Anlagendaten, Sicherungen, Importaktionen, Timerzustände und
Laufzeitreadbacks werden privat unter `data/docs/betrieb/` geführt. Private
Reviewreceipts bleiben unter `reviews/private/`, generierte Prüfarbelege unter
`artifacts/`. Diese Pfade sind keine öffentlich verfügbaren Downloadziele.
Die am 29.10.2026 ausgelagerten ursprünglichen Dokumente sind lokal unverändert
mit Quellcommit und SHA256-Manifest erhalten; sie bleiben außerdem in der
Git-Historie. Der [Dokumentationsindex](../README.md) verlinkt ausschließlich
öffentlich vorhandene Dokumente.

Qualifiziertes produktives Lernen, ein fairer prospektiver Vergleich gegen beide
Referenzintegrationen und belastbare Langzeitspeichermessungen bleiben unabhängig
von Tests oder Review zu erbringen. Maßgeblich ist der vorab eingefrorene
[Validierungsplan](validierung.md).
