# Historische Prüfstände und Nachweisgrenzen

Stand der Zusammenfassung: 29.10.2026. Diese Angaben wurden aus den bisherigen
versionierten Release- und Prüfberichten übernommen. Sie beschreiben damalige
Prüfungen; die Dokumentationsneuordnung ist weder ein neuer vollständiger
Integrationsreview noch eine erneute Laufzeitprüfung.

Ergänzung vom **30.10.2026**: Der korrigierte Entwicklungskandidat für fortlaufende
Quellenbindung und Qualitätsaufnahme hat die [Codex-Quellabnahme](#codex-quellabnahme-des-korrigierten-entwicklungskandidaten)
auf `05f90ea49d1fb124c9f16e1382921d3726f76022` bestanden. Dies ist keine
produktive Installation oder Betriebsfreigabe.

Die anschließende lokale Überarbeitung von Hoststatus, Auswertung und
Qualitäts-CLIs ist **nicht** durch R18 abgedeckt. Ihre Nachweise stehen im
folgenden Abschnitt; die historische Quellabnahme bleibt unverändert erhalten.

## Lokale Nacharbeit nach der Quellabnahme

Ausgangsstand: `5a53b08474a78999b6bfb65523b1785ae9823a54`, 30.10.2026.
Geprüfter Implementierungsstand: `261cd972834174b3e390aeb55e25f12b70a78b4d`
(Hostschutz `9e3dbb3`, gemeinsame Auswahl `dd4e0d1`, Qualitätsadapter `261cd97`).
Die nachfolgende Workflow-/Statusdokumentation ändert diese Pythonbytes nicht.
Die gezielte Untersuchung bestätigte zwei Varianten eines weiteren
Hoststatusfehlers: Statusverzeichnisse in der Originalablage konnten das
Wiederöffnen des Archivs verhindern; ein Statusziel konnte die zuvor gelesene
Hostkonfiguration ersetzen. Beide Fälle wurden ausschließlich in temporären
Verzeichnissen reproduziert. Die drei Regressionen für vorhandenes/nicht
vorhandenes Archiv sowie die Konfigurationskollision scheitern am unveränderten
Ausgangscode; private Daten und produktive Dienste wurden nicht verwendet.

Der korrigierte Runner prüft Statusverzeichnis, alle Jobnachweise und Lock vor
Verzeichnisanlage gegen Quellarchiv, Hostkonfiguration, konfigurierte Eingaben
und Programme. Die Auswerter verwenden eine gemeinsame Auswahlfunktion für den
jüngsten verfügbaren Prognoseversuch; die Qualitäts-CLIs teilen begrenztes
JSON-Lesen und die Prüfung vorhandener Qualität ohne gegenseitigen CLI-Import.
Guardpolicy, Lern- und Qualitätsgates bleiben unverändert.

Drei Implementierungs- und zwei davon getrennte Nachreview-Subagenten wurden mit
**GPT-6.1-Sol/high** beauftragt. Der fokussierte Nachreview fand zusätzlich einen
statischen Aliasfall zwischen konfigurierter und aufgelöster Archivwurzel; er
ist im gemeinsamen Ausgabevalidator und im Datasetexport ebenfalls vorab
gesperrt. Vier neue Gegenproben scheiterten vor dieser Korrektur; drei bestehende
Vergleichsfälle bestanden bereits. Das war eine Schutzvertragsverletzung,
kein Nachweis zusätzlicher Originalkorruption. Die Nachprüfung umfasste die
[Inventur der Schreibwege](review-fehlerfamilien.md), gemeinsame Auswahl und
Qualitätsadapter einschließlich ihrer Verbraucher. Sie ist kein neuer externer
hashgebundener Vollreview und keine Produktivfreigabe.

Nach Korrektur meldeten die beiden fokussierten Nachreviews keine offenen
konkreten Befunde in ihrem Umfang. Die abschließende Vollsuite bestand mit
**2.230 Tests ohne Skips**, **90,88 % kombinierter Abdeckung** und unverändertem
90-%-Gate. Die 23 vorhandenen SQLite-ResourceWarnings bleiben bestehen. Ruff,
`pip check`, vier HA-gesperrte CLI-Importprüfungen und der Dokumentationsabgleich
bestanden. Die geänderten Markdowntexte wurden gerendert; alle 111 lokalen
Linkziele waren vorhanden. Eine zusätzliche Writerfamilienprüfung bestand mit
679 Tests, der unabhängige Writer-Nachreview mit 150 gezielten Tests.

Lokale Nachweise liegen unter `artifacts/learning-support-followup/`:
`host-before.log`, `final-full-tests.log`, `final-coverage.json` und
`final-code-manifest.json`. Das Manifest bindet die 15 geänderten Pythondateien
dieser Überarbeitung; es ist kein externer Reviewreceipt. Es erfolgten kein Push,
Main-Merge, Release oder produktives HA-/Hostdeployment. Die Auslagerung der
Offlineanalyse bleibt der separat beschriebene Folgeschritt; Quellenpins werden
nicht gelockert und die Guardpolicy bleibt unverändert.

## Aktueller Releasebezug

[0.2.19](../releases/release-0.2.19.md) aktualisiert die HA-Geräte-API und
die Serviceimplementierung. Implementierungscommit `8dbf980` bestand lokal
**1.729 Tests ohne Skips** unter Python 3.14 / HA Core 2026.10.4, Ruff und
`pip check`. Eine neue Coveragezahl oder ein externer Review wird aus diesem
Lauf nicht abgeleitet. Release-CI, Artefakte und Installation benötigen eigene
Nachweise; frühere Receipts gelten nicht automatisch für diesen Stand.

Releasecommit `de9c832da394b7d6b0ebeb041a73cad274012224` wurde als `v0.2.19`
veröffentlicht. [Main-CI](https://github.com/togo42/Adaptive-Solar/actions/runs/40896868759)
und [Tag-CI](https://github.com/togo42/Adaptive-Solar/actions/runs/40896869542)
bestanden jeweils mit 1.729 Tests ohne Skips, 90,86 % beziehungsweise 90,88 %
kombinierter Abdeckung und erfolgreichen HA-freien Archivhostjobs.
Wheel, Quellpaket und Integrations-ZIP stimmen in allen 38 Komponenten-Dateien
mit dem Releasequellstand überein; alle vier veröffentlichten Artefakte wurden
nach Download bytegleich geprüft. Ein regulär installierter Wheel bestand
30 Modulimporte mit den vorhandenen gepinnten HA-Testabhängigkeiten.

Die Installation über natives HACS mit einem Core-Neustart wurde auf einer
bestehenden HAOS-/Core-2026.10.4-Installation nachgeprüft. Komponentenbytes,
geladene Einträge, Registryreferenzen, Optionen, Historien, Tagesbeginnwerte,
Energy-/Dashboardkonfiguration und neue Prognosen wurden abgeglichen.
Konfigurationsprüfung und aktive Repairs waren unauffällig; im begrenzten
Logreadback gab es keine Adaptive-Solar-Fehler oder blockierenden Startupmeldungen.
Konkrete Anlagendaten, Komponentenrückweg und Laufzeitreceipts bleiben unter
ignoriertem `data/`. Dies ist ein begrenzter Installationsnachweis.

## Vorheriger Release 0.2.18

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

## Codex-Nachreview der Haupt-CLI-Korrektur

R6 prüfte `1723f2227e184fc2b3e6a87bfb787c77c2c73d41` vollständig durch
Codex GPT-6.1-Sol/high: 209 öffentliche Texte, 44 Quellblöcke sowie Initialisierung
und Abschluss, 46 abgeschlossene Turns, keine Compaction oder nativen Tools.
Die native/API-/Quellenprüfung einschließlich unabhängigem Replay bestand.
Payload-SHA256:
`d1c5ccba1dbfcb1b1589fd93df037c1db359951a3d4f77d2da50fdb24e0b37eb`;
Receipt-SHA256:
`674d5fe997cb04304b6ea3969330ce04a00b4c63497ffed5cc49115bbf0aaf4b`.
Rohbelege: `reviews/private/continuous-quality-codex-r6/`; Audit:
`artifacts/continuous-quality/codex-r6-closeout.json`.

Das Urteil war `blocked` wegen eines mittleren Befunds R6/AS-001: Die
Rohbericht-Aufnahme las bei `state_changed` das mutable `new_state.last_reported`.
Der Code übernimmt nun `last_updated` für diesen Originalbericht; unveränderte
`state_reported` behalten weiterhin den expliziten Ereigniswert. Fehlende
Zustände bleiben fehlend. Energieverarbeitung und Lerngates ändern sich nicht.

Der gewöhnliche synchrone Burst reproduzierte den Befund in HA Core 2026.10.4
zunächst nicht: Diese Callbackpfade werden sofort ausgeführt. Ein früher
registrierter nativer Listener kann jedoch vor dem Eltern-Callback synchron
weitere Berichte auslösen und dessen Stateobjekt verändern. Alle 15 entsprechenden
Regressionen scheiterten am alten Code mit zwei Sekunden zu spätem Originalbericht.
Nach Korrektur bestehen sowohl diese Fälle als auch 15 gewöhnliche Burstfälle
für Power, Energie, GHI, Temperatur und Wind, jeweils Initial-, Attribut- und
erzwungene Änderungen. Zusammen mit vorhandenen Export-, Messfenster- und
Gültigkeitstests bestanden 128 gezielte native Tests. Die installierte native
`State.last_reported`-Dokumentation bestätigt die verwendete Semantik.
Vorher-/Nachher-Belege liegen unter
`artifacts/continuous-quality/review-r6-before-reentrant.log` und
`review-r6-fixes-targeted.log`. Die finale Vollsuite bestand mit **1.957 Tests
ohne Skips** und **90,78 % kombinierter Abdeckung**, unverändertes 90-%-Gate;
weiterhin 23 SQLite-ResourceWarnings. Ruff und der Dokuabgleich bestanden.
Finale Testausgabe/Coverage: `artifacts/continuous-quality/review-r6-fixes-full-tests.log`
und `review-r6-fixes-coverage.json`.

R6 ist keine positive Abnahme. Historische Archive werden nicht umgeschrieben;
der neue Producerstand benötigt erneut einen hashgebundenen Vollreview.
Keine produktive HA-/Hoständerung oder Aktivierung ist erfolgt.

## Weiterer Codex-Nachreview und Standortbindung des EPS-Replays

R7 auf `2e208a0884ffa16fa2736d3700f8ed6d34f62782` wurde beim
Serverneustart vor dem Schlussurteil unterbrochen. 45 abgeschlossene Turns
belegen keinen vollständigen Review. Das ursprüngliche Receipt blieb unverändert;
der separate lokale Abbruchnachweis steht unter
`artifacts/continuous-quality/codex-r7-interrupted.json`. Receipt-SHA256:
`b0390eadfd37122d1a6c0ca5e646996438340bdd3f5c40ac30d2b4e3c86d2431`.

R8 prüfte denselben unveränderten Quellstand mit der inzwischen installierten
Codex-CLI **0.166.0**, weiterhin **GPT-6.1-Sol/high**: 209 öffentliche Originaltexte,
44 Quellblöcke plus Initialisierung und Abschluss, 46 abgeschlossene Turns,
keine Compaction oder nativen Tools. Der unabhängige Audit bestätigte vollständige
Quellen-/Prompt-/Antwortbindung, native Modellbindung sowie die unveränderte
Treiberbasis und den exakten lokalen Transportpatch. Payload-SHA256:
`cb84713b78f981023697e4a67aa999261beb198f40ac0ec3fd4943c350d7ff9b`;
Receipt-SHA256:
`b25dd970e3fd1d650f266ba2eeff97b97cb45c47976dfac5108e7c36ca3489a2`.
Rohbelege: `reviews/private/continuous-quality-codex-r8/`; Audit:
`artifacts/continuous-quality/codex-r8-closeout.json`.

Das Urteil blieb `blocked` wegen des mittleren Befunds R8/AS-001:
Der Host-EPS-Replay prüfte die ursprünglichen Anfragekoordinaten nicht gegen
die Standortdatei. Nun müssen beide Koordinaten vorhanden, endlich, gültig und
exakt gleich sein, bevor die Mitgliedsphysik beginnt. Abweichende Produkte
bleiben mit Diagnose ausgeschlossen; ohne verwendbares Produkt endet die CLI
mit Fehlercode 1. Produkte verschiedener Standorte können keine Familienmischung
bilden. Ein neuer unpassender Abruf erlaubt keinen Rückfall auf den älteren
passenden Abruf desselben Produkts. Anbieter-Rasterkoordinaten ersetzen nicht
die ursprünglichen Anfragekoordinaten.

Die neuen Gegenproben ergaben am alten Stand **28 Fehler und einen gültigen
Vergleichsfall**. Nach Korrektur bestanden **108 gezielte Tests** für Replay,
Ensemblearchive, Wahrscheinlichkeiten und Ausgabepfade. Die Fälle umfassen
fehlende/ungültige Koordinaten, falsche Standortdateien, gemischte Produktstandorte,
jüngere unpassende Abrufe und einen gültigen CLI-Lauf trotz abweichender
Anbieter-Rasterkoordinaten. Lokale Belege:
`artifacts/continuous-quality/review-r8-before.log` und
`review-r8-fixes-targeted.log`. Ruff bestand; der Betriebsleitfaden wurde abgeglichen.
Die finale Vollsuite bestand mit **1.986 Tests ohne Skips**, **90,78 % kombinierter
Abdeckung** und unverändertem 90-%-Gate; weiterhin 23 SQLite-ResourceWarnings.
Finale Ausgabe und Coverage stehen unter
`artifacts/continuous-quality/review-r8-fixes-full-tests.log` und
`review-r8-fixes-coverage.json`.

R8 ist keine positive Abnahme; die Standortkorrektur benötigt einen neuen
hashgebundenen Vollreview. Keine produktive HA-/Hoständerung oder Aktivierung
ist erfolgt.

## Codex-Nachreview und zyklische Winkel bei Endpunktfenstern

R9 prüfte `29ec05d` mit Codex GPT-6.1-Sol/high, CLI 0.166.0, vollständig:
209 Originaltexte, 44 Quellblöcke plus Initialisierung und Abschluss,
46 abgeschlossene Turns, keine Compaction oder nativen Tools. Der unabhängige
Audit bestätigte erneut Quellen, Prompts, Antworten, Modellbindung und
Treiber-/Transportpatchbindung. Payload-SHA256:
`779299d4cfe2133094b77f04384de8f7ff5045829f76fd291a3295a9b952d143`;
Receipt-SHA256:
`144a2f10c3c38c5ba239323478d7e8adca664ae99e84e17eae3d18ecb66683eb`.
Rohbelege: `reviews/private/continuous-quality-codex-r9/`; Audit:
`artifacts/continuous-quality/codex-r9-closeout.json`.

Das Urteil blieb `blocked` wegen eines mittleren Befunds R9/AS-001:
`integrate_original` mittelte den Azimut in Grad linear. Am Norddurchgang
konnten 359° und 1° so fälschlich 180° ergeben und der Vektorrichtung
widersprechen. Der Gradwert wird nun aus dem zeitgewichteten Sinus-/Kosinusvektor
abgeleitet; reine Gradfeatures werden vor der Mittelung in Vektoren überführt.
Unvollständige Vektoren und mittlere Vektorlängen `<= 1e-12` sperren das Fenster.
Die ursprünglichen Vektormittel, gemessene Dauer und Energiedifferenzen bleiben
erhalten. Der Join und sein Fit werden aus Originalzellen neu aufgebaut;
historische Archive werden nicht umgeschrieben.

Die ersten 19 neuen Gegenproben ergaben am alten Stand **16 Fehler und drei
gültige Vergleichsfälle**. Nach Korrektur bestanden alle 19; ergänzte Fälle
prüfen nahezu aufgehobene Richtungen, fehlende Vektorkomponenten und das
Ausschließen einer Messlücke aus Winkel- und Baselinegewichten. Die Regressionen
umfassen außerdem zeitlich ungleiche Gewichte, reine Grad-/Vektorfeatures,
Endpunktjoin, unveränderte Originale/Energie und die tatsächliche
Schatten-Baselinekompatibilität im Lerner. Belege:
`artifacts/continuous-quality/review-r9-before.log` und
`review-r9-angle-targeted.log`. Messvertrag und Implementierungsvertrag wurden
abgeglichen. Ruff bestand.
Die breitere gezielte Suite bestand mit **210 Tests**, die finale Vollsuite mit
**2.013 Tests ohne Skips**, **90,79 % kombinierter Abdeckung** und unverändertem
90-%-Gate; weiterhin 23 SQLite-ResourceWarnings. Ausgaben/Coverage:
`artifacts/continuous-quality/review-r9-fixes-targeted.log`,
`review-r9-fixes-full-tests.log` und `review-r9-fixes-coverage.json`.

R9 ist keine positive Abnahme. Die Winkelkorrektur benötigt erneut einen
hashgebundenen Vollreview. Keine produktive Änderung oder Aktivierung ist erfolgt.

## Codex-Nachreview und unabhängig verfügbare NWP-Vergleichsarme

R10 prüfte `7c3a45c` vollständig durch Codex GPT-6.1-Sol/high, CLI 0.166.0:
209 Originaltexte, 44 Quellblöcke plus Initialisierung und Abschluss,
46 abgeschlossene Turns, keine Compaction oder nativen Tools. Der unabhängige
Audit bestätigte erneut Quellen-/Prompt-/Antwortbindung, native Modellbindung
und Treiber-/Transportpatchbindung. Payload-SHA256:
`1738b7277c11ba7bf1ee2a697348ce24c22e2a99b96a136b6edf5f670f1d9faa`;
Receipt-SHA256:
`655af8a3b5e03c381e9a1a88e45817ab4468d175bd5f70aae5634a451ae54531`.
Rohbelege: `reviews/private/continuous-quality-codex-r10/`; Audit:
`artifacts/continuous-quality/codex-r10-closeout.json`.

Das Urteil blieb `blocked` wegen eines mittleren Befunds R10/AS-001:
Der reine NWP-Arm wurde erst nach dem Erfolg der operativen Physik archiviert.
Wenn alle GHI-korrigierten Teilintervall-Proxys ausfielen, fehlten dadurch auch
weiterhin berechenbare Original-NWP-Mitglieder. Die Engine berechnet und
archiviert diese jetzt vor den operativen Abbruchstellen mit eigenen
Originalwetterfeatures. Die operative Lücke und echte NWP-Physiklücken bleiben
erhalten; historische Ausgaben werden nicht ergänzt.

Die bereinigten 17 Gegenproben scheitern am unveränderten Enginecode aus
`7c3a45c`. Sie verwenden synthetische Wetterwerte mit echter Physik ohne
Ausfallmock, alle unterstützten
Mehrschrittauflösungen 2/4/6/12, ein/zwei Wettermodelle und ein/zwei Stufen.
Ein nativer Coordinatorfall prüft zusätzlich getrennte leere operative Arme,
vorhandenen NWP-Arm, Original-Wetterausgabezeit und Archiv-Roundtrip ohne
Trainings-/Messzeilen. Die erste Testmatrix hatte vier unzulässige
8-Schritt-Konfigurationen enthalten; diese sind kein Fehlernachweis.
Vorher-Beleg: `artifacts/continuous-quality/review-r10-before.log`.
Die bestehende Schattenkohortenprüfung zählt nun ausdrücklich nur ihre
operativen/Schattenschritte, ohne den unabhängig vorgezogenen NWP-Arm.
Die Modellarmverträge wurden abgeglichen; Ruff bestand.
Die gezielte Suite bestand mit **185 Tests**, die finale Vollsuite mit
**2.030 Tests ohne Skips**, **90,85 % kombinierter Abdeckung** und unverändertem
90-%-Gate; weiterhin 23 SQLite-ResourceWarnings. Ausgaben/Coverage:
`artifacts/continuous-quality/review-r10-fixes-targeted.log`,
`review-r10-fixes-full-tests.log` und `review-r10-fixes-coverage.json`.

R10 ist keine positive Abnahme. Die Korrektur benötigt erneut einen
hashgebundenen Vollreview. Keine produktive Änderung oder Aktivierung ist erfolgt.

## Codex-Nachreview und Inodeschutz der Append-Collector

R11 prüfte `3f7ad68` vollständig durch Codex GPT-6.1-Sol/high, CLI 0.166.0:
209 Originaltexte, 44 Quellblöcke plus Initialisierung und Abschluss,
46 abgeschlossene Turns, keine Compaction oder nativen Tools. Der unabhängige
Audit bestätigte Quellen-/Prompt-/Antwortbindung, native Modellbindung und
Treiber-/Transportpatchbindung. Payload-SHA256:
`8cfa497924ca238ee61b96a58bbda454ba81256b6b77f4634d883a456b1111a4`;
Receipt-SHA256:
`6422c0a1de965d33b5febee6053c1880aee8b38e785102e98a768a55e8b74b0d`.
Rohbelege: `reviews/private/continuous-quality-codex-r11/`; Audit:
`artifacts/continuous-quality/codex-r11-closeout.json`.

Das Urteil blieb `blocked` wegen eines mittleren Befunds R11/AS-001:
Die Append-Collector `capture_actuals.py` und `capture_ha.py` konnten einen
Programm-Inode über Hardlinks unter `data/` verändern. Sie verwenden jetzt den
gemeinsamen Programmschutz vor Netzabruf und Append; unmittelbar vor dem Schreiben
prüfen sie zusätzlich den geöffneten Deskriptor gegen alle Eingaben sowie
Programm-/Ressourcendateien. Zielpfad und Deskriptor müssen denselben Inode
bezeichnen; Appendziele brauchen genau einen Link. Die Vollständigkeitsprüfung
des Prognosecollectors liest nun ebenfalls den bereits gesperrten Deskriptor.
Lock, bestehende Rohzeilen und unvollständige letzte Zeilen behalten ihre Regeln.

Alle ersten **24 Gegenproben scheiterten am alten Stand**: beide Collector,
Programm-/Komponenten-/Ressourcendateien, Aliase vor/während des Abrufs sowie
geöffnete geschützte Inodes trotz anschließend harmlos aussehendem Zielpfad.
Mapping- und Qualitätsdateien sind ebenfalls abgedeckt. Zwei weitere Fälle
prüfen den Pfadaustausch bei einem unbeteiligten Inode mit nur einem Link.
Neun ergänzte Fälle prüfen verschobene Programm-/Ressourcen-/Eingabe-Inodes:
Vor dem Abruf erfasste Geräte-/Inode-Identitäten bleiben über den Abruf hinweg
geschützt, auch wenn der ursprüngliche Pfad durch eine neue Datei ersetzt wurde.
Die Proben verwenden ausschließlich wegwerfbare lokale Dateien; keine
Produktivdatei wurde angehängt oder ein Netzabruf ausgeführt. Beleg:
`artifacts/continuous-quality/review-r11-before.log`.
Der Leitfaden nennt die gemeinsame Helferabhängigkeit; isolierte CLI-Testkopien
enthalten diese jetzt mit. Ruff bestand.
Die gezielte Suite bestand mit **300 Tests**, die finale Vollsuite mit
**2.065 Tests ohne Skips**, **90,85 % kombinierter Abdeckung** und unverändertem
90-%-Gate; weiterhin 23 SQLite-ResourceWarnings. Ausgaben/Coverage:
`artifacts/continuous-quality/review-r11-fixes-targeted.log`,
`review-r11-fixes-full-tests.log` und `review-r11-fixes-coverage.json`.

R11 ist keine positive Abnahme. Die Schreibschutzkorrektur benötigt erneut einen
hashgebundenen Vollreview. Keine produktive Änderung oder Aktivierung ist erfolgt.

## Weitere Codex-Läufe und geschütztes Dataset-Exportziel

R12 auf `699e777e4f4dc74822f4e660c162ed54e59447d4` scheiterte im
Schlussreview: Der native API-Guard wies einen unvollständigen Antwortstrom
zurück. 46 abgeschlossene Vorabturns ersetzen kein Schlussurteil. Receipt-SHA256:
`7cbb81142b88e0f407f45d24e03ce0d35655c838d1a8cd8d488a23230aa4f994`.
Lokaler Fehlernachweis: `artifacts/continuous-quality/codex-r12-failure.json`.
Kein Gate wurde gelockert.

R13 prüfte denselben unveränderten Quellstand durch Codex GPT-6.1-Sol/high,
CLI 0.166.0, vollständig: 209 Originaltexte, 45 Quellblöcke plus Initialisierung
und Abschluss, 47 abgeschlossene Turns, keine Compaction oder nativen Tools.
Der unabhängige Audit bestätigte Quellen-/Prompt-/Antwortbindung, native
Modellbindung sowie Treiber-/Transportpatchbindung. Payload-SHA256:
`294d8f21132e6f39d552f639eb3ab4be236399264b162f68699ea48c35f2cc71`;
Receipt-SHA256:
`f4a0c69af6994bcab8effd3f7e4ab73e5b92cb7ad930eba9dde2922b9b9624c8`.
Rohbelege: `reviews/private/continuous-quality-codex-r13/`; Audit:
`artifacts/continuous-quality/codex-r13-closeout.json`.

Das Urteil blieb `blocked` wegen eines mittleren Befunds R13/AS-001:
Ein neues Dataset-Exportverzeichnis innerhalb der Quelloriginale konnte deren
strikte Verzeichnisprüfung blockieren. `ArchiveStore.export_dataset` verlangt
nun ein lexikalisch und aufgelöst außerhalb der gesamten Quellarchivwurzel
liegendes Ziel. Das wird vor Beginn und erneut unmittelbar vor dem Anlegen
des Exportbaums geprüft. Bereits bestehende Ziele werden weiterhin abgelehnt.

Alle **16 neuen Gegenproben scheiterten am alten Stand**. Sie prüfen beide
Exportlayouts, interne Wurzel-/Original-/Präfixziele, normalisierte Pfade,
Symlinkaliase ins Archiv, lexikalisch interne Ziele mit Symlink nach außen,
einen während der Originalprüfung umgebogenen Zielparent und den echten CLI-Pfad.
Nach Ablehnung müssen Originalbytes und Pins unverändert, Wiederöffnen und
`verify` erfolgreich und weitere Collectoraufnahmen möglich sein. Die gezielte
Suite bestand mit **137 Tests**. Belege:
`artifacts/continuous-quality/review-r13-before.log` und
`review-r13-fixes-targeted.log`. Speicherkontrakt und Betriebsleitfaden wurden
abgeglichen. Ruff bestand.

Die finale Vollsuite bestand mit **2.081 Tests ohne Skips**, **90,86 %
kombinierter Abdeckung** und unverändertem 90-%-Gate; weiterhin 23
SQLite-ResourceWarnings. Finale Ausgabe/Coverage:
`artifacts/continuous-quality/review-r13-fixes-full-tests.log` und
`review-r13-fixes-coverage.json`.

R13 ist keine positive Abnahme. Die Exportkorrektur benötigt einen frischen
hashgebundenen Vollreview. Keine produktive Änderung oder Aktivierung ist erfolgt.

## Codex-Nachreview und geschützter Observation-Export

R14 prüfte `2b327f5` durch Codex GPT-6.1-Sol/high, CLI 0.166.0, vollständig:
209 Originaltexte, 45 Quellblöcke plus Initialisierung und Abschluss,
47 abgeschlossene Turns, keine Compaction oder nativen Tools. Der unabhängige
Audit bestätigte Quellen-/Prompt-/Antwortbindung, native Modellbindung und
Treiber-/Transportpatchbindung. Payload-SHA256:
`547658ea107ae8faa19b7fab6a7fb87cc8313ac14d197e4d98d749d93b9b7dda`;
Receipt-SHA256:
`7a91397919e24f46bff73d2891551323fabf0f7cd32aa94db99f49f1c7c3824d`.
Rohbelege: `reviews/private/continuous-quality-codex-r14/`; Audit:
`artifacts/continuous-quality/codex-r14-closeout.json`.

Das Urteil blieb `blocked` wegen eines mittleren Befunds R14/AS-001:
Auch `archive.py export-observations` erlaubte neue interne Ziele. Ein Dateiname
wie `originals/export.json.gz` blockierte danach die strikte Originalprüfung,
selbst bei leerem Export. Dieser CLI-Pfad verwendet nun die gemeinsame
Ausgabeprüfung vor Archivöffnung, vor temporärer Ausgabe und unmittelbar vor
Veröffentlichung. Interne lexikalische/aufgelöste Ziele sowie Programm-/Eingabealiase
bleiben gesperrt; bestehende Ziele werden weiterhin nicht überschrieben.

Alle **13 Gegenproben scheiterten am alten Stand**. Sie prüfen leere und
befüllte Archive, interne Wurzel-/Original-/Präfixziele, Aliase und lexikalisch
interne Pfade mit Symlink nach außen, die Prüfung vor Archivöffnung sowie nach
dem Öffnen beziehungsweise nach der Captureiteration umgebogene Zielparents.
Nach Ablehnung müssen Originalbytes, Wiederöffnen, `verify` und weitere Aufnahme
erhalten bleiben. Vier zusätzliche positive Fälle prüfen externe JSONL-Roundtrips
mit/ohne Datensätze und externe Parentaliase samt Ablehnung bestehender Ziele.
Vorher-Beleg: `artifacts/continuous-quality/review-r14-before.log`.
Speicherkontrakt und Betriebsleitfaden wurden abgeglichen; Ruff bestand.

Die gezielte Suite bestand mit **226 Tests**, die finale Vollsuite mit
**2.098 Tests ohne Skips**, **90,86 % kombinierter Abdeckung** und unverändertem
90-%-Gate; weiterhin 23 SQLite-ResourceWarnings. Ausgaben/Coverage:
`artifacts/continuous-quality/review-r14-fixes-targeted.log`,
`review-r14-fixes-full-tests.log` und `review-r14-fixes-coverage.json`.

R14 ist keine positive Abnahme. Die Observation-Exportkorrektur benötigt erneut
einen hashgebundenen Vollreview. Keine produktive Änderung oder Aktivierung ist erfolgt.

## Codex-Nachreview und native Gegenprüfung des Kontinuitätsbefunds

R15 prüfte `e07d636` durch Codex GPT-6.1-Sol/high, CLI 0.166.0, vollständig:
209 Originaltexte, 45 Quellblöcke plus Initialisierung und Abschluss,
47 abgeschlossene Turns, keine Compaction oder nativen Tools. Der unabhängige
Audit bestätigte Quellen-/Prompt-/Antwortbindung, native Modellbindung und
Treiber-/Transportpatchbindung. Payload-SHA256:
`f924d6dc5c02887e98fdf605ba2d924af42cff48d6909e902e6eb9137c9e4b45`;
Receipt-SHA256:
`bdccf36aa7d1ae6155333ceba6fc4fea697a1c78f5c99cf62b314eec7ad70b7e`.
Rohbelege: `reviews/private/continuous-quality-codex-r15/`; Audit:
`artifacts/continuous-quality/codex-r15-closeout.json`.

Das statische Urteil war `blocked` wegen R15/AS-001 (mittel): Ein früherer
HA-Listener könne aus einem ungültigen Zählerzustand synchron einen numerischen
Folgebericht erzeugen, dessen Callback vor dem ungültigen Eltern-Callback ein
Delta freigebe. **Dieser Ablauf ist für die geprüften Core-Versionen widerlegt.**
Die native Core-Implementierung `EventBus.async_fire_internal` stellt beim
gesetzten `_dispatching` verschachtelte Ereignisse in `_event_queue` und liefert
sie erst nach Abschluss des laufenden Dispatchs aus. Der aktuelle HA-State kann
schon weiter sein; die Integration verarbeitet trotzdem den ungültigen Bericht
vor seinem Folgeereignis. Der ungültige Bericht bricht die Kontinuität;
der erste gültige Folgebericht ankert neu.

Alle **24 nativen Gegenproben bestehen bereits mit dem unveränderten
Coordinator aus `e07d636`**: `unknown`, `unavailable`, NaN, falsche Einheit,
`restored` und Entfernung, jeweils Null-/Positivenergie und eine/drei
verschachtelte Wiederkehr. Ein zuerst registrierter nativer Entity-Listener
erzeugt die Folgeereignisse. Die Tests prüfen Callback-Reihenfolge, Zähleranker,
erhaltene gültige spätere Deltas und die wirklich an `qualified_interval`
übergebenen Grenzen. Keine Zeile darf die ungültige Phase überbrücken.
Eine vorsorgliche zusätzliche Coordinator-Sperre wurde deshalb verworfen;
die Produktionsdatei ist bytegleich zum geprüften Stand. Beibehalten sind die
Regressionen und diese Entscheidungsbegründung.

Die installierte native Laufzeit ist Core 2026.10.4; zusätzlich wurden die
unveränderten Wheels 2026.10.2 (deklarierte Mindestversion) und .3 ausschließlich
auf diesen Quellpfad geprüft. Alle drei `homeassistant/core.py` sind bytegleich
und stimmen mit ihren Paket-`RECORD`-Hashes überein:
SHA256 `1fe2fcfb91fbb6edfb4450dad3ae5ebc4e325664770fedbd607d103d91ce4f19`.
Der Quellabschnitt `EventBus.async_fire_internal` hat SHA256
`cb5835817a5abc803f9bbb1992e1de1840cb0c820c6c9ccd832f3d1749d509bf`.
Das ist keine erneute vollständige native Testqualifikation von Core .2/.3.
Lokale Gegenbelege:
`artifacts/continuous-quality/codex-r15-native-counterevidence.json`,
`review-r15-before.log` und `review-r15-fixes-targeted.log`.
Die breitere native Suite bestand mit **159 Tests**; Ruff bestand.
Die finale Vollsuite bestand mit **2.122 Tests ohne Skips**, **90,86 %
kombinierter Abdeckung** und unverändertem 90-%-Gate; weiterhin 23
SQLite-ResourceWarnings. Finale Ausgabe/Coverage:
`artifacts/continuous-quality/review-r15-final-full-tests.log` und
`review-r15-final-coverage.json`.

R15 wird nicht nachträglich zu einer positiven Abnahme umgedeutet. Der Befund
wird anhand der nativen Gegenbelege zurückgewiesen; Regressionen und
Dokumentation benötigen einen frischen Vollreview. Keine produktive Änderung
oder Aktivierung ist erfolgt.

## Codex-Nachreview und fehlerhafte Wetter-JSON-Strukturen

R16 prüfte `8d32af9` durch Codex GPT-6.1-Sol/high, CLI 0.166.0, vollständig:
209 Originaltexte, 45 Quellblöcke plus Initialisierung und Abschluss,
47 abgeschlossene Turns, keine Compaction oder nativen Tools. Der unabhängige
Audit bestätigte Quellen-/Prompt-/Antwortbindung, native Modellbindung und
Treiber-/Transportpatchbindung. Payload-SHA256:
`d1ff105fa1dbcfcfbdf723cbae2adebb9be3e7050a52422b24617b58f911a5eb`;
Receipt-SHA256:
`a9a64cb28462651affe9c0d8593df5ca9128d929a8448e45683eab7c5f3fb456`.
Rohbelege: `reviews/private/continuous-quality-codex-r16/`; Audit:
`artifacts/continuous-quality/codex-r16-closeout.json`.

Das Urteil blieb `blocked` wegen eines mittleren Befunds R16/AS-001:
Falsche Container bei syntaktisch gültigem Provider-JSON konnten als
`AttributeError` den vorgesehenen Parserfehler-/Archivpfad verlassen. Der Parser
verlangt nun ein Antwortobjekt sowie Objektstrukturen für `hourly_units` und
`hourly`; falsche Formen lösen `WeatherError` aus. Der bestehende Fehlerpfad
bewahrt damit auch diese unveränderten JSON-Werte mit HTTP-/Fehlerstatus.
Cachefreigabe, ursprünglicher Empfang und Modellverfügbarkeit bleiben getrennt.

Die 39 neuen Gegenproben ergaben am alten Stand **33 Fehler und sechs bereits
korrekt behandelte Vergleichsfälle**. Sie umfassen Parserfehler sowie tatsächliche
Journalaufnahme unter nativem HA mit/ohne zulässigen Altcache. Geprüft werden
unveränderte JSON-Werte, HTTP 200 mit `status=failed`, expliziter Parserfehler,
keine neue verfügbare Receipt-ID und aktiver Export ohne Drops/Schreibfehler.
Die gezielte Suite bestand mit **178 Tests**. Belege:
`artifacts/continuous-quality/review-r16-before.log` und
`review-r16-fixes-targeted.log`. Implementierungsvertrag und Betriebsleitfaden
wurden abgeglichen; Ruff bestand.

Die finale Vollsuite bestand mit **2.161 Tests ohne Skips**, **90,87 %
kombinierter Abdeckung** und unverändertem 90-%-Gate; weiterhin 23
SQLite-ResourceWarnings. Finale Ausgabe/Coverage:
`artifacts/continuous-quality/review-r16-fixes-full-tests.log` und
`review-r16-fixes-coverage.json`.

R16 ist keine positive Abnahme. Die Strukturkorrektur benötigt erneut einen
hashgebundenen Vollreview. Keine produktive Änderung oder Aktivierung ist erfolgt.

## Codex-Nachreview und absolutes UTC-Raster der Referenzstunden

R17 prüfte `86c35c7` durch Codex GPT-6.1-Sol/high, CLI 0.166.0, vollständig:
209 Originaltexte, 45 Quellblöcke plus Initialisierung und Abschluss,
47 abgeschlossene Turns, keine Compaction oder nativen Tools. Der unabhängige
Audit bestätigte Quellen-/Prompt-/Antwortbindung, native Modellbindung und
Treiber-/Transportpatchbindung. Payload-SHA256:
`59b1e2d155e8830d2376da0dee396b3189037efe6c5406b2aea527689429f1a9`;
Receipt-SHA256:
`8fb88d123134fe0261c825a70cf982de4f43482150d636039c3d9f6b57dcfd49`.
Rohbelege: `reviews/private/continuous-quality-codex-r17/`; Audit:
`artifacts/continuous-quality/codex-r17-closeout.json`.

Das Urteil blieb `blocked` wegen eines mittleren Befunds R17/AS-001:
Referenzservice und Forecastcollector prüften volle Stunden vor statt nach der
UTC-Normalisierung. Beide prüfen jetzt erst den absoluten UTC-Stundenbeginn.
Äquivalente Darstellungen bleiben gleichwertig, Originalsnapshotkeys und
Energiewerte unverändert. Doppelte absolute Stunden werden weiter abgelehnt.
Die übrigen Stunden-/Viertelstundenprüfungen wurden auf diese Reihenfolge
abgeglichen; sie normalisieren bereits vor ihrer Rasterprüfung.

Die 24 neuen Gegenproben ergaben am alten Stand **20 Fehler und vier gültige
Vergleichsfälle**. Sie prüfen den nativen Antwortservice, den Collectorjoin
gleichwertiger Darstellungen, positive/negative Halb- und Viertelstundenoffsets,
einen Sekundenoffset, falsch ausgerichtete lokale Vollstunden und doppelte
absolute Stunden. Die gezielte Suite bestand mit **195 Tests**. Belege:
`artifacts/continuous-quality/review-r17-before.log` und
`review-r17-fixes-targeted.log`. Aufnahmeleitfaden und Implementierungsvertrag
wurden abgeglichen; Ruff bestand.

Die finale Vollsuite bestand mit **2.185 Tests ohne Skips**, **90,88 %
kombinierter Abdeckung** und unverändertem 90-%-Gate; weiterhin 23
SQLite-ResourceWarnings. Finale Ausgabe/Coverage:
`artifacts/continuous-quality/review-r17-fixes-full-tests.log` und
`review-r17-fixes-coverage.json`.

R17 ist keine positive Abnahme. Die UTC-Rasterkorrektur benötigt erneut einen
hashgebundenen Vollreview. Keine produktive Änderung oder Aktivierung ist erfolgt.

## Codex-Quellabnahme des korrigierten Entwicklungskandidaten

**R18 akzeptiert, ohne Befunde:** Codex **GPT-6.1-Sol/high**, installierte CLI
**0.166.0**, Quellstand `05f90ea49d1fb124c9f16e1382921d3726f76022`.
Die Abnahme umfasst 209 öffentliche Originaltexte einschließlich der acht
Service-/Timervorlagen, 2.676.906 Payloadbytes, 45 Quellblöcke sowie
Initialisierung und Abschluss: **47 vollständig abgeschlossene Turns**.
Das endgültige Urteil lautet `mergeable`, `findings=[]`.

Payload-SHA256:
`eeec9aacfdc17c97097248de307232b30eb26ae9d99c783df2877c7eab1b14d1`.
Receipt-SHA256:
`79050525eae64e4f5126f3ba9a60bfaa8a496699b364a1df3cc3810e3da17a5d`.
Review-JSON-SHA256:
`652c9ae36855c89acde3d75590a3769f1b53b55c8e8e52a614f3cb33899a75e8`.

Der nachgelagerte unabhängige Audit bestand: sämtliche Originaldateien waren
zum Abschluss bytegleich zum lokalen Checkout, alle Quellblöcke wurden exakt
rekonstruiert und native Prompts/Antworten, Modell, Effort, CLI sowie vollständige
API-Abschlüsse verifiziert. **Keine Compaction, nativen Tools oder Hintergrundtasks.**
Der Audit prüfte zusätzlich die eingefrorene Toolingbasis `4ba01bb` und den
exakten lokalen I/O-Deadlinepatch des isolierten Treibers; dieser Patch wurde
nicht Teil des öffentlichen Kandidaten. Rohbelege:
`reviews/private/continuous-quality-codex-r18/`; unabhängiger Abschluss:
`artifacts/continuous-quality/codex-r18-closeout.json`.

In den vorangegangenen Läufen wurden **14 bestätigte mittlere Befunde behoben**
und jeweils mit Regressionen und Dokumentation committed. R15/AS-001 wurde mit
nativen Ereignisfolgen und identischen Core-Paketquellen zurückgewiesen; eine
vorsorgliche Produktionsänderung blieb nicht bestehen. Technisch fehlgeschlagene
oder unterbrochene Läufe behalten ihren negativen/unvollständigen Nachweisstatus.
R18 ersetzt diese Historie nicht, sondern akzeptiert den neuen eingefrorenen
Gesamtstand.

Die finale lokale Vollsuite bestand mit **2.185 Tests ohne Skips**, **90,88 %
kombinierter Abdeckung** und unverändertem 90-%-Gate. Ruff und Dokuabgleich
bestanden; weiterhin 23 SQLite-ResourceWarnings. Testausgabe/Coverage:
`artifacts/continuous-quality/review-r17-fixes-full-tests.log` und
`review-r17-fixes-coverage.json`. Der erneut ausgeführte tatsächliche lokale
CLI-Probelauf akzeptierte zwei synthetische Stunden bei bytegleich gebliebener
Rohaufnahme: `artifacts/continuous-quality/rehearsal-accepted/manifest.json`.
Diese synthetischen Quellenpins sind keine physische Quellenqualifikation.

Die Prüfung ist statisch; Codex führte keine Tests aus. PNG-Rendering war nicht
Teil des Textreviews. Die lokale QA und der synthetische Probelauf belegen weder
Prognoseüberlegenheit noch qualifiziertes produktives Lernen oder reale
Archivkapazität. Kein Push, Merge, Release, HA-/Hostdeployment, Neustart oder
Timeraktivierung erfolgte. Der nächste betriebliche Schritt bleibt der separat
vorbereitete, begrenzte Probelauf mit tatsächlich geprüften Quellenbindungen.

Diese nachträgliche Statusdokumentation liegt ausdrücklich außerhalb des
eingefrorenen Reviewumfangs. Implementierung, Tests und übrige Dokumentation
bleiben bytegleich zum akzeptierten Quellstand.

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
