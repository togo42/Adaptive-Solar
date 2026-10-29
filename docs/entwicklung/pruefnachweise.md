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
