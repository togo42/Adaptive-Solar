# Adaptive Solar 0.2.24: veröffentlichte Schattenfenster-Diagnose

Stand: 05.11.2026, **veröffentlicht und installiert; strenge vollständige
Produktabnahme noch nicht verifiziert**.
Der [Release v0.2.24](https://github.com/togo42/Adaptive-Solar/releases/tag/v0.2.24)
bindet unveränderlich Tagcommit `f21ad29c8341f9d784e686b4a74ab9a6a4097c93`.
Er führt die AF-036-Vorbereitung `9c9a709` mit dem veröffentlichten
[0.2.23](release-0.2.23.md) zusammen. Der native Nachinstallationsreadback bestätigt
**0.2.24 auf Core 2026.11.0 mit vier geladenen Einträgen** und exakt alle
44 Komponentenoriginale des Releases. Lokale Tests, Paketprüfung,
Main-CI, Veröffentlichung, öffentliche Assetprüfung und die unten abgegrenzte
native Probe sowie Branch-/Tag-CI sind abgeschlossen. Ein erfolgreicher Release
ersetzt keine vollständige Produktabnahme. Deren offene Eingangsnachweise sind
unten von der abgeschlossenen Installation und Erhaltungsprüfung getrennt.

## Ausschließlich additive, lesende Diagnose

Der bestehende Prognosedatenstatus-Sensor und die redigierte Integrationsdiagnose
erhalten je Ausgangsstufe den Geschwisterblock
`learning.<Stufe>.beam_shade_windows`. Er zeigt alle **aktuell gespeicherten**
Sonnenfenster, nicht alle jemals beobachteten Fenster und keine erfundenen
leeren Rasterzellen. Der aktuelle Block `beam_shade` bleibt unverändert.

- Schema 1, `scope=stored_solar_windows`, Raster `10° × 5°`, höchstens
  **648 Einträge je Stufe**, numerisch nach Azimut/Höhe sortiert und vollständig
  (`truncated=false`). Alle Einträge teilen den tatsächlichen Schatten-
  Auswertungszeitpunkt `evaluated_at`, nicht den möglicherweise älteren Fitcutoff.
- Wirksamer Faktor, Kandidat, Tages-MAD, Freigabegrund und Proben-/Tageszähler
  trennen zeitlich verwendbare, abgelaufene, noch nicht verfügbare und
  unqualifizierte Legacybelege. Ohne verwendbare Proben bleiben Kandidat und
  MAD `null`. Ein neutraler Rückfall `1.0` ist durch `released=false` von einem
  qualifiziert gelernten neutralen Faktor unterscheidbar.
- Ein fehlender Block bedeutet nicht verfügbar; `total=0` bezeichnet dagegen
  eine gelieferte leere Tabelle. Nachts bleibt der gespeicherte Umfang sichtbar.
  Ein älteres `as_of` rekonstruiert keine bereits verdrängte Historie.
- Keine Rohproben, Faktorenzeitreihen oder Freigabeereignislisten; die abgetrennte
  Projektion mutiert weder Tabellen noch Freigaben. `learning` bleibt vollständig
  vom regulären Recorder ausgeschlossen. Keine neue Entität, Option, Aktion,
  Wetterabfrage oder persistente Tabelle.

Der vollständige [Feldvertrag](../technik/schattenfenster-diagnose.md),
die [Bedienung](../anwendung/bedienung.md) und der
[Datenschutz](../anwendung/datenschutz.md) erläutern Interpretation und Grenzen.
Auch aggregierte Faktoren können lokale Verschattungsmuster offenlegen und
müssen vor öffentlicher Weitergabe geprüft werden.

## Unveränderte Lern-, Speicher- und Lieferverträge

Alle **14 bisherigen `BeamShadeTable`-Methoden bleiben AST-identisch**, darunter
`status_for()`, `to_dict()` und `from_dict()`. Die Erweiterung liegt ausschließlich
als lesende Methode und Geschwistereintrag im Coordinator-Lernstatus vor; sie
wird nicht in archivierte Schattenentscheidungen injiziert. Für den finalen
Release wurde dieser Erhaltungsvertrag frisch abgeglichen: Nach Entfernen
der beiden neuen Methoden entspricht der Schatten-AST dem Vorgänger; nach Entfernen
des einen Diagnoseeintrags gilt dasselbe für den Coordinator. Alle weiteren
Komponentenoriginale außer der Manifestversion sind bytegleich zu 0.2.23.

Unverändert bleiben `beam_shade_v1`/Speicherschema 3, alte Leser,
`learning_feature_contract=beam-shade-table-v1`, sämtliche Konfigurations-,
Historien- und Schattenfingerprints, Lern-/Freigabegates, Fit-Eingaben und
Fit-Signatur, Modellanwendung und Prognoseberechnung. Kein Historienreset,
keine Datenmigration, kein Umschreiben ursprünglicher Messintervalle,
Tagesstart-Snapshots/-kurven, Comparisonoriginale, Archive, Pins oder Checkpoints.
Ein normaler Neustart baut flüchtige Fits wie bisher aus der erhaltenen validen
Lernbasis neu auf; unveränderte Lernregeln bedeuten keine Persistenz von Fitobjekten.

Der HA-native ML-Startpfad aus 0.2.23, dessen Runtimeanforderungen,
scikit-learn-Pin und **unveränderliche Dependency-Release-URL** bleiben erhalten.
Es wird kein neues Dependency-Artefakt eingeführt. Plattform-, Paketnetzwerk-,
Lizenz- und Fehlergrenzen gelten weiter gemäß
[ML-Liefervertrag](../technik/ml-runtime-bundle.md).

## Upgrade und Rückweg

Vor einem tatsächlichen Update sind Komponentenstand, Konfiguration und eine
Erhaltungsbaseline frisch festzuhalten. Vorhandene Einträge weiterverwenden;
keine Integration löschen, keine Lernbasis zurücksetzen und keine direkten
`.storage`-Writes. Veröffentlichte und heruntergeladene Artefakte müssen vor der
Installation gegen den finalen Release geprüft werden.

**Ausgeführter Installationsweg:** Wegen der zuvor fehlenden
Marketplace-Erstwarnungsbestätigung des API-Kontos hat der Nutzer den manuellen
Download und **genau einen Core-Neustart** selbst ausgeführt und bestätigt.
Die Installation ist abgeschlossen und nativ abgeglichen. Der Agent hat die
Kontowarnung weder akzeptiert noch umgangen und wiederholt weder Download noch
Neustart. Eine kontogebundene Zustimmung wird nicht auf andere Konten übertragen.

Auch dieser rein diagnostische Pythonquellwechsel ändert den **vollständigen
Producerhash**. Vor Dateiwechsel/Neustart den aktuellen Quellenbindungsstand frisch
prüfen. Die bei 0.2.23 bereits halb offen geschlossenen alten v2-Quellenperioden
bleiben geschlossen; weder erneut öffnen noch alte Pins verlängern oder ersetzen.
Nur tatsächlich noch offene Perioden vor dem Wechsel am exakten realen UTC-Cutover
halb offen schließen. Neue Producerpins benötigen eine eigene Prüfung und Freigabe;
der Release erzeugt oder qualifiziert keine neuen Bindungen. Alte Originale,
Quellumgebungen, Konfigurationsanker und Attestationen bleiben erhalten.

Nach dem normalen Core-Neustart sind geladene Einträge, Identitäten, Optionen,
Energy-/Dashboardbezüge, vor dem Cutoff abgeschlossene Messintervalle,
eingefrorene Tagesstartoriginale, Comparisonoriginale und neue Diagnoseblöcke
frisch zu prüfen. Regulär fortgeschriebene Forecastrepräsentanten sind von
unveränderlichen Originalen zu unterscheiden; vollständige Storebytegleichheit
ist kein sachgerechtes Abnahmekriterium. Keine Quellenfrische oder neuen
Trainingslabels erzwingen. Falls Timer pausiert werden, deren ursprünglichen
Zustand gesondert nach bestandener Abnahme wiederherstellen.

Der reine Code-Rückweg verwendet die erhaltenen geprüften 0.2.23-Komponentenbytes
mit unverändertem Store. Auch dabei Quellwechsel und Bindungen sauber abgrenzen.
Originalarchive und fortgeschriebene Checkpoints nicht aus alten Sicherungen
überschreiben. Ein danach fehlender Diagnoseblock muss als nicht verfügbar gelten.

## Aktuelle Prüfung und Nachweisgrenzen

### Installation, Erhaltung und offene vollständige Abnahme

Der frische native Readback bestätigt Core 2026.11.0, Adaptive Solar 0.2.24,
exakte Komponentenbytes, den Python-Producerhash und die Runtimeanforderungen des
unveränderten veröffentlichten Releases. Alle vier Einträge sind geladen. Die vor dem Wechsel
abgeschlossenen Messintervalle, Konfigurations-/Historien-/Schattenfingerprints,
Lerntabellen, eingefrorenen Tagesstartoriginale und Comparisonoriginale sind
erhalten, ebenso Exportgenerationen, Entity-/Unique-IDs, Geräte, Optionen und
Energy-Einstellungen. Die neuen Schattenfensterlisten sind vollständig und
konsistent mit den gespeicherten Tabellen. Das qualifiziert keine neuen Quellen.
Der frische globale Healthread meldet keine Repairs und gültige Konfiguration.

**Die strenge vollständige aktuelle Produktabnahme ist dennoch nicht verifiziert.**
Im jüngsten vollständigen Capture sind zwei konfigurierte Leistungseingänge zum
tatsächlichen Forecastzeitpunkt `missing_stale_or_invalid`. Zwei Exportprüfungen
sind positiv; zwei bestehen `configured_inputs_valid_at_original_issue` nicht. Dadurch bleiben
die beiden Eingangsgates und der von sämtlichen Exportprüfungen abhängige native
ML-Bootstrapnachweis negativ. Dieses abgeleitete Gate ist **kein Beleg eines
fehlgeschlagenen ML-Bootstraps**, eines Unloads oder Resets. Ein erneuter
unabhängiger Runtimeimport im produktiven Core wurde nicht separat geprüft;
es wurde kein positives `acceptance.json` erzeugt.

Ein früherer Abgleich hatte positive Erhaltungs- und Exportprüfungen, aber ein
negatives Gesamtflag wegen eines privaten UTC-Stringvergleichs. Ausschließlich
der private Abnahmereader wurde korrigiert: gleiche absolute Zeitpunkte mit
unterschiedlichen Offsets werden nach UTC kanonisiert. **140 Guardtests** bestehen;
neue eingefrorene Auswertung und Gates stimmen überein. Die negativen Originale
bleiben erhalten. Das ist weder eine HA-Codeänderung noch eine Gatelockerung;
der echte Frischebefund im jüngsten Capture bleibt negativ.

Der nächste Schritt ist ein neuer lesender Abgleich, sobald echte gültige frische
Leistungsberichte bei einem normalen Forecast vorliegen. Später gelesene Zustände
heilen keine früheren Forecastcutoffs. Keine erzwungenen Quellenupdates, neuen
Positivlabels, Gate-Lockerungen, Lern-/Archivresets oder weiteren Neustarts sind
dafür vorgesehen. Der Agent hat keine Optionen, Policy oder Timer geändert.

### Software-, CI- und Artefaktprüfung

- Gesamtsuite: **3.235 bestanden, zwei optionale reale Rust-Kerneltests
  ausgelassen**, 30 nicht unterdrückte SQLite-ResourceWarnings; kombinierte
  Zeilen-/Zweigabdeckung **91,55 %** bei unverändertem 90-%-Gate. Dieser Lauf
  verwendet Python 3.14.4, **Core 2026.10.4 / Testplugin 0.13.375**, nicht Core 2026.11.
- [Main-CI 42103043766](https://github.com/togo42/Adaptive-Solar/actions/runs/42103043766):
  **alle Jobs erfolgreich**, **3.237 bestanden, keine Skips**, **91,55 %**
  kombinierte Abdeckung und 29 nicht unterdrückte Warnungen; außerdem
  **42 native Differential-/Projektionstests bestanden**. Der Unterschied zum
  lokalen Gesamtlauf sind dessen zwei optionale Rust-Auslassungen, keine
  ausgelassenen HA-Tests. Auch die [Branch-CI 42103043761](https://github.com/togo42/Adaptive-Solar/actions/runs/42103043761)
  und [Tag-CI 42103932484](https://github.com/togo42/Adaptive-Solar/actions/runs/42103932484)
  sind für denselben unveränderten Releasecommit erfolgreich. Die Tag-CI meldet
  ebenfalls **3.237 Tests ohne Skips / 91,55 %** und 42 native Differentialtests.
- Separate Offlineprobe im erhaltenen offiziellen amd64/Musl-Image mit
  **Core 2026.11.0 / Python 3.14.10**: 36 native Modulimporte, zwei gesunde
  Bootstrapdurchläufe ohne Installer, Fit/Predict, alle 648 Fenster,
  Nichtmutation, Schema-3-Roundtrip und synthetischer Coordinator-Forecast
  einschließlich Sensor-/Diagnoseprojektion bestanden. Keine vollständige
  native Config-Entry-/Plattform-Setup-/Reloadsuite, kein erneuter
  Dependencydownload und kein produktiver HA-Nachweis. Eine fehlerhafte erste
  Probe mit unvollständigem Testdouble blieb als negatives Original erhalten;
  der Wiederholungslauf verwendet Core `ConfigEntry`, ohne Produktkorrektur.
- Wheel, sdist und Integrations-ZIP enthalten dieselben **44 Komponentenoriginale**;
  36 Module wurden aus einer regulären separaten Wheelinstallation importiert.
  Ruff, `pip check` und Paket-/Pfadprüfungen bestanden. Die Dependencyauslieferung
  bleibt unverändert. Alle vier veröffentlichten Releaseassets wurden erneut
  heruntergeladen und **bytegleich** zu den geprüften lokalen Artefakten bestätigt.
- Unabhängiger integrierter Subagentenreview: keine Befunde im öffentlichen
  Releaseumfang, 29 gezielte Diagnosetests bestanden. Der zusätzliche private
  Abnahmereader wurde wegen einer zu engen Legacy-Alias-Zählergrenze korrigiert;
  danach seinerzeit **129 lokale Guardtests ohne Skips**, keine produktive Änderung.
  Die spätere reine UTC-Readerkorrektur mit 140 Tests ist oben getrennt beschrieben.
- Der neue Grok-4.7/high-`all/chunks`-Versuch wurde wegen **nativer Compaction
  abgewiesen**. Er ist ausdrücklich **keine gültige externe Gesamtquellabnahme**;
  der fehlgeschlagene Kontextaudit und seine Originale bleiben erhalten.

Der vollständige Python-Producerhash des veröffentlichten Releases ist
`e665f51a3795ec6bef994a04cdf7078c9ea57d84b470fc0085f669911001b7a7`.
Der frische schmale Archivhost-Read bestätigt weiterhin geschlossene unveränderte
Altperioden, unveränderte Pins und ursprüngliche Timerzustände; die separate
Beobachtungsaufnahme bleibt deaktiviert. Es wurden keine Policy- oder
Timeränderungen ausgeführt. Das ist ein begrenzter, nicht atomarer Readback,
kein neuer umfassender Archiv-/Checkpointaudit.

## Öffentliche Releaseassets

Die SHA256-Werte binden die tatsächlich heruntergeladenen vier Assets des
unveränderlichen Releases, nicht einen produktiven Installationsstand:

| Asset | SHA256 |
| --- | --- |
| `adaptive_solar.zip` | `667aaa4a48d684c45bca82a675da6c583122f2e8f6c3bf442303525a69cf8883` |
| `adaptive_solar_ha-0.2.24-py3-none-any.whl` | `1d0adde838a470cc14a2a3514beb828e6b93121f7a30e61bee4c89021fa06093` |
| `adaptive_solar_ha-0.2.24.tar.gz` | `e8ba2d5d13a76a05ec0136ac0360f83a08176417e05203f0ffb74a75e12ce16c` |
| `SHA256SUMS` | `5de62cd84528ea9a3f8a9a0ef1c6e3912ae5eeb0c550472b575a32dec8c2ed6b` |

## Noch offene Nachweise und getrennte Folgearbeiten

Der [Vorbereitungsnachweis für `9c9a709`](../technik/schattenfenster-diagnose.md#7-historischer-vorbereitungsnachweis-für-9c9a709)
ist ausschließlich historisch. Seine Testzahlen, AST-Vergleiche und lokalen
Reviews sind **keine** aktuelle Abnahme des zusammengeführten 0.2.24-Releases.
Installation und begrenzter produktiver Erhaltungsreadback sind abgeschlossen;
Branch-/Main-/Tag-CI, Veröffentlichung und öffentliche Assetprüfung sind oben
getrennt belegt. Die strenge vollständige Produktabnahme bleibt wegen der
aktuellen Eingangsgates und abhängigen Export-/ML-Startnachweise offen.
Baselineaufnahme, frühere positive Teilprüfungen und geschlossene Altperioden
ersetzen keinen vollständigen aktuellen Abgleich und qualifizieren keine neuen Quellen.

Diese nach Veröffentlichung aktualisierten Statusangaben ändern weder den
unveränderlichen Tag noch seine Komponenten-/Paketbytes und sind kein neuer Build.
Sie erweitern keinen früheren Review auf neue Dokumentationsbytes; der fehlgeschlagene externe
Grok-Kontextaudit bleibt ungültig.

AF-036 im getrennten **HA-Config**-Projekt bleibt ein Consumer-Folgeauftrag:
keine Dashboardressource, Karte oder vollständige Fensteransicht wird hier
aktualisiert. Die separate positive Zeitliste angenommener ML-Ziele ist nicht
enthalten und lässt sich nicht aus Ablehnungslisten rekonstruieren.
Externe Archivhostdienste, Runtime und Quellenfreigaben sind ebenfalls keine
automatische Folge dieses Integrationsreleases.

Öffentliche Nachweise enthalten nur bereinigte Zusammenfassungen; private
Laufzeitoriginale und Installationsprotokolle bleiben privat. Tests, Reviews,
Reproduzierbarkeit und Erhaltung beweisen weder physische Quellenqualität noch
produktives Lernen oder einen Genauigkeitsvorsprung gegenüber Referenzintegrationen.
