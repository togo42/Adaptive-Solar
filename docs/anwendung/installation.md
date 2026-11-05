# Adaptive Solar installieren und aktualisieren

Stand: 05.11.2026; Anleitung für Version 0.2.23. Dessen [Releasehinweise](../releases/release-0.2.23.md)
trennen Vorbereitung, Veröffentlichung und HA-Abnahme. Veröffentlichungs- und
historische Testangaben stehen in den [Prüfnachweisen](../entwicklung/pruefnachweise.md). Die hier beschriebenen Schritte
werden vom Betreiber auf der eigenen Installation ausgeführt. Projektprüfungen und
ein vorhandenes Release ersetzen die Prüfung der eigenen Plattform nicht.

## 1. Plattform und Voraussetzungen

| Kombination | Nachweis und Grenze |
| --- | --- |
| Core 2026.10.2 / Python 3.14 | Native HA-Tests, Testplugin 0.13.373 |
| Core 2026.10.3 / Python 3.14 | Native HA-Tests, Testplugin 0.13.374 |
| Core 2026.10.4 / Python 3.14 | Native HA-Tests, Testplugin 0.13.375; dokumentierte HAOS-Installation |
| Core 2026.11.0 / HAOS amd64 / Python 3.14.10 | Frische HA-native ML-Installation über öffentliche Runtime-URL, nativer Fit/Predict, Hashablehnung und Offline-Zweitstart im offiziellen Image bestanden; Marketplaceinstallation und begrenzte produktive Erhaltung abgenommen, keine vollständige native Testsuite behauptet |
| HAOS amd64, CPython 3.14, Musl ≥1.2 | Ab 0.2.23 automatische Lieferung des geprüften Binärpakets; externer Bau bleibt Aufgabe der Releasepflege, nicht des Betreibers |
| Linux/glibc | Entwicklungs-/HA-Core-Testumgebungen geprüft; kein pauschaler Nachweis beliebiger Containerinstallationen |
| ARM/aarch64, Raspberry Pi, andere Python-ABIs | Bisher nicht qualifiziert; kein passender Build-/Installationsnachweis im Projekt |

Die Metadatenuntergrenze 2026.10.2 entspricht dem ältesten geprüften Core. Sie ist keine
Zusage für alle späteren Versionen. Der native Testvertrag verwendet Core 2026.10.4;
die Nachweise für .2/.3 stammen aus früheren Releases. Versionsdetails stehen in den [Prüfnachweisen](../entwicklung/pruefnachweise.md). Runtimepins stehen im
[Manifest](../../custom_components/adaptive_solar/manifest.json) und
[ML-Liefervertrag](../../custom_components/adaptive_solar/runtime_requirements.json):
pvlib 0.16.1 und scikit-learn 1.9.1. Deren transitive Abhängigkeiten löst HA
anhand der originalen Paketmetadaten und Coreconstraints auf; sie sind nicht
pauschal durch das Integrationsmanifest festgepinnt.
Ein früherer erfolgreicher Import anderer Versionen reicht nicht.

**Core-Update ab 2026.11:** Der frühere Lieferpfad unter `/config/deps` entfällt.
Ab 0.2.23 prüft Adaptive Solar vor Coordinator-/Storeaufbau die lokale exakte
ML-Version und den nativen Learnerimport. Nur bei fehlender Bibliothek verwendet
es HAs Requirementsmanager: auf qualifiziertem Musl den hashgebundenen Binärliefer-
Container, auf qualifiziertem glibc das normale PyPI-Requirement. Eine falsche oder
beschädigte vorhandene Version wird nicht im laufenden Prozess ersetzt.
`skip_pip`/`skip_pip_packages` werden respektiert; deaktivierte Paketinstallation
kann eine Neueinrichtung daher bewusst blockieren. Keine Einträge oder Lernstores
löschen. [Liefervertrag](../technik/ml-runtime-bundle.md).

Benötigt werden Internetzugriff auf Open-Meteo, korrekte Standortdaten, Zeitzone
und String-/Ausgangsparameter. Lokale Messsensoren sind optional. Ohne geeignete
Energiehistorie arbeitet die Integration mit Physik statt mit einem gelernten Modell.
Der optionale Originaldatenexport ab 0.2.16 ist standardmäßig
ausgeschaltet; ein Archivhost wird für die Prognose nicht benötigt. Für einen
bewusst eingerichteten Archivbetrieb zusätzlich freien HA-Datenträgerplatz,
privaten Hostspeicher, administrative HA-Leseberechtigung und einen
Sicherungs-/Wiederherstellungsplan vorsehen. Logische Puffergrenzen und zusätzliches
Diskbudget stehen im [Speichervertrag](../archiv/archive-storage-contract.md); der
[Archivbetrieb](../archiv/archivbetrieb.md) beschreibt die getrennte Einrichtung.

Die kostenlose Wetter-API ist für nichtkommerzielle Nutzung vorgesehen;
[Datenflüsse und Bedingungen](datenschutz.md).

## 2. Vorbereiten

1. Unter **Einstellungen → System → Reparaturen → Systeminformationen** Core,
   Python und Architektur erfassen. Die Pythonversion einer SSH-App gehört nicht
   zwingend zu Core.
2. Eine aktuelle Home-Assistant-Sicherung erstellen und deren Abschluss prüfen.
   Vor einem Upgrade zusätzlich die bisherige Integrationsversion notieren.
3. Für 0.2.23 Internetzugriff auf GitHub-Releaseassets und PyPI erlauben. Das
   Dependency-Artefakt muss bereits veröffentlicht und unverändert verfügbar sein.
   Kein manueller Wheelbau oder SSH-/Dockerzugriff ist für die normale Installation
   vorgesehen. Ältere Versionen benötigen weiterhin den historischen
   [HAOS-Lieferweg](haos-installation.md).
4. Marketplace vorab einmal mit dem installierenden Benutzerkonto öffnen und
   die Erstnutzungswarnung selbst lesen/bestätigen. Das gilt auch für das Konto
   eines API-/MCP-Zugangs; `can_install=true` allein belegt die Bestätigung nicht.
   Bei externem Archivbetrieb diese Voraussetzung **vor** Timerpause und
   Periodenschließung klären. Ein Agent darf die Warnung nicht stellvertretend
   akzeptieren oder umgehen; alternativ führt der Betreiber Download/Neustart
   selbst aus und lässt danach den tatsächlichen Stand prüfen.

## 3. Über Marketplace installieren

1. In **Marketplace** **Benutzerdefinierte Repositories** öffnen.
2. `https://github.com/togo42/Adaptive-Solar` als Typ **Integration** hinzufügen.
3. Eine veröffentlichte Version auswählen und herunterladen.
4. Home Assistant neu starten; anschließend die Protokolle auf Fehler zu
   `adaptive_solar`, `pvlib` und `sklearn` prüfen.
5. **Einstellungen → Geräte & Dienste → Integration hinzufügen → Adaptive Solar**
   öffnen. Standort, Ausgangsstufen und Strings gemäß [Bedienung](bedienung.md)
   einrichten. Bestehende Einträge werden beim Upgrade weiterverwendet.

Marketplace ist ab Core 2026.11 bereits integriert; dort kein zusätzliches HACS
installieren. Auf älteren Coreversionen gilt HACS nach seiner
[historischen Anleitung](https://www.hacs.xyz/docs/use/). `hacs.json` bleibt die
kompatible Metadatendatei. Projektcode und Abhängigkeiten sind getrennte Lieferteile:
Das Vorab-Release `v0.2.23-runtime.1` enthält ausschließlich die Binär-/Quellartefakte
für den Installer; als Integration das reguläre Release **v0.2.23** auswählen.

## 4. Manuelle Alternative

Das gewünschte Tag/Release lokal beziehen. Den vollständigen Ordner
`custom_components/adaptive_solar/` einschließlich `core/`, Übersetzungen, Markenbild
und Lizenz unter `<HA-Konfigurationsverzeichnis>/custom_components/adaptive_solar/`
ablegen. Das Verzeichnis mit `configuration.yaml` ist die Konfigurationswurzel;
im Corecontainer ist es normalerweise `/config`.

Keine zweite Ordnerebene `adaptive_solar/adaptive_solar` erzeugen. Alte vollständige
Kopien außerhalb von `custom_components` sichern: Auch ein umbenannter oder
versteckter Komponentenordner kann vom HA-Loader gefunden werden. Abhängigkeiten
wie oben vorbereiten; dann neu starten und über die native Oberfläche einrichten.
Es ist kein `adaptive_solar:`-Eintrag in `configuration.yaml` erforderlich.

## 5. Erfolg prüfen

- Der Eintrag unter Geräte & Dienste ist geladen und erzeugt Geräte und Sensoren.
- Bei einer Ausgangsstufe gibt es bei Neueinrichtung ein Gerät mit zehn Sensoren;
  Alt-Gesamtsensoren können als ausgeblendete Kompatibilitätsanzeigen bestehen bleiben.
- Resttag und erreichbare Folgetage haben plausible Werte innerhalb der Ausgangsgrenze.
  Tag 0 darf am ersten Einrichtungstag ohne vorherigen Mitternachtssnapshot fehlen.
- `Prognosedatenstatus` und seine Attribute erklären Eingänge und Abdeckung.
  `physics` oder ein kalter Lerner ist bei einer neuen Anlage erwartbar.
- Nur bei bewusst aktiviertem Originaldatenexport ab 0.2.16:
  `archive_export`-Status prüfen und die Antwortaktion
  `adaptive_solar.export_archive` mit einem Administratorzugang lesen.
  Der Schalter **Originaleingaben archivieren (privater Exportpuffer)** steht
  im Standort-/Optionsdialog und bleibt beim Update standardmäßig aus.
  Erfolgreiche Prognosen allein belegen keine vollständige Archivaufnahme.
- HA-Konfigurationsprüfung und Reparaturen auf neue Probleme prüfen. Für die eigene
  Installation verbleibt die Qualifikation der Messquellen und später des Lernens.

Fehlender Wetterzugang oder unpassende Binärabhängigkeiten können bereits das Setup
verhindern. Diagnosepfade: [Fehlerbehebung](bedienung.md#7-fehlerbehebung-und-support).

## 6. Aktualisieren, zurückkehren und entfernen

**[Version 0.2.23](../releases/release-0.2.23.md):** In Marketplace aktualisieren,
danach einmal Core neu starten und Abschnitt 5 prüfen. Vorhandene Einträge, IDs,
Messhistorie und echte Tagesstartwerte weiterverwenden. Eine gesunde vorhandene
scikit-learn-Version 1.9.1 bleibt unberührt; ein frischer kompatibler Corecontainer
wird automatisch versorgt. Andere/kaputte Installationen und im notwendigen
Installationszweig unbekannte Liefer-ABIs werden klar abgelehnt, nicht durch
globale Importpfade oder Compilerbau verdeckt.
Die neuen Integrations-Pythonbytes ändern den Producerhash: externe qualifizierte
Quellenperioden vor dem Wechsel begrenzen und neue Bindungen gesondert belegen.
Marketplace aktualisiert nicht den separaten Archivhost. Der Austausch der
Liefertechnik ist keine neue fachliche Lern- oder Quellenfreigabe.

Vor Updates die Versionshinweise lesen, sichern und verwendete Geräte-/Sensorverweise
notieren. Für 0.2.10 erklärt [die Releasebeschreibung](../releases/release-0.2.10.md) die
Anzeige-Migration und den Featurevertragswechsel. Für 0.2.11 sind zusätzlich
die [Schutzprüfung und Althistorienqualifikation](../releases/release-0.2.11.md#upgrade-von-0210)
zu beachten: Historie bleibt erhalten, frühere Abregelungsfreiheit wird nicht
nachträglich technisch bestätigt. Für 0.2.12 beschreibt die
[Releasebeschreibung](../releases/release-0.2.12.md#upgrade-von-0211) den Wechsel auf
`beam-shade-table-v1`: Alte Forecastfeatures und abgeleitete Lerner starten neu;
passende Messintervalle und tatsächlich ausgegebene Tagesbeginn-Snapshots bleiben
erhalten. Die neue Schattentabelle beginnt leer und neutral. Komponentenstand und
Lernstores vorab sichern, falls für einen Rückweg das alte Lernarchiv benötigt wird.
Für 0.2.14 bleiben Runtimepins und Lernfeaturevertrag unverändert. Die
[Reparaturen](../technik/forecast-repairs.md) erhalten historische Tagesstartwerte mit
Originalprovenienz und begrenzen kleine negative Nachtstrahlung. Bereits verlorene
Tageswerte brauchen einen expliziten Originalimport. Nach Marketplace-Download einmal
Core neu starten; kein Core-/OS-Upgrade.

[Version 0.2.15](../releases/release-0.2.15.md) ergänzt [Messkontinuität/Endpunktfenster](../technik/measurement-learning.md),
[Fit-/Wetterfallback und Diagnosen](../technik/forecast-resilience.md), einen ausschließlich
beobachteten [frühen Bias-Kandidaten](../technik/early-bias-shadow.md) und das
[Modellvergleichsarchiv](../technik/model-comparison-archive.md). Die optionalen
[Physik-/Nowcastparameter](../technik/physics-learning-options.md) haben neutrale Standards;
aktive Physikänderungen verändern die strenge Historienbindung. Passende alte
Messhistorie erhält keinen nachträglich erfundenen Kontinuitätsnachweis; ältere
Schattentabellen behalten unbelegte Schema-1/2-Proben nur diagnostisch; aktive
Freigaben brauchen neue zeitlich qualifizierte Proben nach Schema 3. Ein Rückweg braucht
weiterhin die gesicherte Komponente und Historie der Zielversion.

[Version 0.2.16](../releases/release-0.2.16.md) ergänzt den optionalen Originaldatenexport
und den externen Archivbetrieb. Exportoption und Hostcollector werden getrennt
eingerichtet; die Option allein verändert weder Physikbindung noch Modellgewichte.
Der kalte Wetterimport läuft über den nativen HA-Importexecutor.

[Version 0.2.17](../releases/release-0.2.17.md) korrigiert den numerischen Vergleich
berechneter Zwischenwerte im Replay. Produktive Physik-/Lernregeln und
Archivdaten bleiben unverändert; Quellversion und Aufnahme müssen weiterhin
zusammenpassen.

[Version 0.2.18](../releases/release-0.2.18.md) speichert vollständige Stundenkurven
zusammen mit künftigen Tagesbeginn-Snapshots. Vorhandene Tagessummen bleiben
erhalten; fehlende alte Kurven werden nicht rekonstruiert. Marketplace aktualisieren
und einmal Core neu starten, ohne Einträge oder Lernstores zurückzusetzen.
Abhängigkeitspins, Physik- und Lerngates ändern sich nicht. Ein Rückweg zu
0.2.17 kann die unverändert gespeicherten Tageswerte und Historie weiter lesen.
Archivhost-Helfer werden separat installiert; ein Marketplace-Update aktualisiert
weder Archivhostdienste noch Dashboardressourcen.

[Version 0.2.19](../releases/release-0.2.19.md) aktualisiert die interne
Geräte-Eigentümerabfrage und die Serviceimplementierung. Der Upgradepfad ist
unverändert: Marketplace-Download und ein Core-Neustart. Konfiguration, Lernhistorie,
Entity-IDs, Prognoseverfahren und Abhängigkeitspins bleiben erhalten.

**[Version 0.2.20](../releases/release-0.2.20.md):**
HA-Integration und externe Archivhosthelfer getrennt aktualisieren. Vor dem
Marketplace-Download sichern, danach einmal Core neu starten und die Erfolgskontrolle
aus Abschnitt 5 durchführen. Der Offline-Support-Guard wird durch das HA-Update
nicht aktiviert; vorhandene Einträge und
Lernhistorien weiterverwenden, keine Reinitialisierung oder direkten Änderungen
an `.storage` vornehmen. Fortlaufende v2-Qualitätsaufnahme benötigt neue
Originalintervalle mit passenden Producerpins und gesondert geprüfte
Konfigurations-, Mess- und Abregelungsbindungen. Alte Originale aus 0.2.18/0.2.19
erhalten durch das Update keine fehlenden Pins. Ein Marketplace-Update installiert
keine externen Hosthelfer und aktiviert keine Archivtimer.

**[Version 0.2.21](../releases/release-0.2.21.md):**
Vor dem Marketplace-Update Komponentenstand und Optionen sichern, danach einmal Core
neu starten und Abschnitt 5 prüfen. Das optionale Nachtprofil
`archive_source_report_profile: night_sparse_v1` wird nur durch ausdrückliche
Optionswahl aktiv. Es ändert weder Anlagenphysik noch Mess-/Lerngates.
Kompakte Qualitätsdiagnosen und die getrennten Hostjobs `actuals`/`references`
benötigen einen eigenen Hostwechsel gemäß [Hostinstallation](../archiv/archiv-host-installation.md).
Vor der Streamtrennung den kombinierten `observations`-Timer deaktivieren und
seinen laufenden Dienst auslaufen lassen; neue Timer erst nach geprüften
Einzelaufnahmen aktivieren. Kombinierte und getrennte Aufnahme nicht parallel
betreiben. Bestehende Originale, Pins und Checkpoints erhalten; neue
Producerhashes nur für neue, gesondert belegte Zeiträume binden.

**[Version 0.2.22](../releases/release-0.2.22.md#upgrade-von-0221-und-rückweg):**
Bestehende Einträge weiterverwenden, Komponentenstand und Historie sichern,
nach dem Marketplace-Download einmal Core neu starten und Abschnitt 5 prüfen.
Abhängigkeitspins und HA-Storeversionen bleiben erhalten. Die strengeren
Snapshotprüfungen können einen vorhandenen Store mit ungültigen Pflichtwerten
schreibgeschützt lassen; gültige Tagessummen verlieren durch eine beschädigte
optionale Stundenkurve allein nicht ihre Gültigkeit. Nicht direkt `.storage`
bearbeiten und alte Werte nicht auf die Grenze zurechtschneiden.

Neue Exporte enthalten den überwachten Messgültigkeitsbeginn. Alte Captures ohne
diesen Beleg können bei konfigurierter Gültigkeitsquelle keine ungesperrte
Leistung für Schattenneulernen qualifizieren. Die neuen Integrationsbytes ändern
den Producerhash: alte v2-Quellenperioden vor dem belegten Wechsel begrenzen und
neue Pins ausschließlich für neue gesondert attestierte Zeiträume verwenden.
Historische Originale nicht umetikettieren. Ein Marketplace-Update ändert weder den
bereits getrennt geprüften Hoststand noch dessen Timer oder Runtime-Manifest.

Historisch für 0.2.13: Featurevertrag, passende Forecast-/Messhistorie,
Schattentabellen und echte Tagesbeginn-Snapshots erhalten. Die
[Releasebeschreibung](../releases/release-0.2.13.md) erklärt die neuen Messabdeckungsregeln
und die additive Ablehnungsdiagnose. Ein vorhandener passender Musl-Payload
bleibt verwendbar; Geräte-, Sensor- und Energy-Zuordnungen benötigen keine Änderung.
Marketplace aktualisiert den Code;
anschließend Core neu starten und obige Prüfung wiederholen. Änderungen an Physik
oder Messbindungen können neue Lernhistorie erfordern. Das Optionsformular lädt
den Eintrag nach Abschluss neu.

Bei Problemen den Eintrag zunächst deaktivieren und die Diagnose sichern. Marketplace kann
eine verfügbare ältere Version erneut herunterladen; manuell den gesamten gesicherten
Komponentenordner zurückspielen. Eine ältere Version kann neuere Historien nicht
zwingend lesen. Deshalb vorab Daten sichern und eine Code-Rückkehr nicht als
garantierte Rückmigration der Historie behandeln. Abhängigkeiten nur anhand des
Zielmanifests und des gesicherten Paketstands zurücksetzen, keine fremden Pakete löschen.

Zum Entfernen zuerst abhängige Automationen, Dashboards und Energy-Verknüpfungen
prüfen, dann den Eintrag in Geräte & Dienste entfernen und bei Bedarf den Code in
Marketplace deinstallieren. **Eintragslöschung ist kein nachgewiesener Datenlöschvorgang**:
Lernstores, Recorder und Sicherungen können Daten behalten; beim optionalen
Originaldatenexport zusätzlich der separate HA-Puffer und externe Archivkopien.
Das Abschalten der Option oder eine Rückkehr zu einer Version ohne Export entfernt diese Daten nicht. Den Umfang einer
vollständigen Löschung beschreibt [Datenschutz](datenschutz.md#4-entfernen-und-aufbewahrung).
