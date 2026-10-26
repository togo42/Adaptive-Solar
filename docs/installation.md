# Adaptive Solar installieren und aktualisieren

Stand: 26.10.2026; Quell- und Referenzrelease 0.2.10. Die hier beschriebenen Schritte
werden vom Betreiber auf der eigenen Installation ausgeführt. Projektprüfungen und
ein vorhandenes Release ersetzen die Prüfung der eigenen Plattform nicht.

## 1. Plattform und Voraussetzungen

| Kombination | Nachweis und Grenze |
| --- | --- |
| Core 2026.10.2 / Python 3.14 | Native HA-Tests, Testplugin 0.13.373 |
| Core 2026.10.3 / Python 3.14 | Native HA-Tests, Testplugin 0.13.374 |
| Core 2026.10.4 / Python 3.14 | Native HA-Tests, Testplugin 0.13.375; dokumentierte HAOS-Installation |
| HAOS amd64, CPython 3.14, Musl 1.2 | Zusätzlicher externer Wheelbau und persistente Lieferung erforderlich; siehe [HAOS-Anleitung](haos-installation.md) |
| Linux/glibc | Entwicklungs-/HA-Core-Testumgebungen geprüft; kein pauschaler Nachweis beliebiger Containerinstallationen |
| ARM/aarch64, Raspberry Pi, andere Python-ABIs | Bisher nicht qualifiziert; kein passender Build-/Installationsnachweis im Projekt |

Die HACS-Untergrenze 2026.10.2 entspricht dem ältesten geprüften Core. Sie ist keine
Zusage für alle späteren Versionen. Versionsdetails und historische Testnachweise
stehen im [Entwicklungsstand](entwicklungsstand.md). Runtimepins stehen im
[Manifest](../custom_components/adaptive_solar/manifest.json): pvlib 0.16.1 und
scikit-learn 1.9.1. Ein früherer erfolgreicher Import anderer Versionen reicht nicht.

Benötigt werden Internetzugriff auf Open-Meteo, korrekte Standortdaten, Zeitzone
und String-/Ausgangsparameter. Lokale Messsensoren sind optional. Ohne geeignete
Energiehistorie arbeitet die Integration mit Physik statt mit einem gelernten Modell.
Die kostenlose Wetter-API ist für nichtkommerzielle Nutzung vorgesehen;
[Datenflüsse und Bedingungen](datenschutz.md).

## 2. Vorbereiten

1. Unter **Einstellungen → System → Reparaturen → Systeminformationen** Core,
   Python und Architektur erfassen. Die Pythonversion einer SSH-App gehört nicht
   zwingend zu Core.
2. Eine aktuelle Home-Assistant-Sicherung erstellen und deren Abschluss prüfen.
   Vor einem Upgrade zusätzlich die bisherige Integrationsversion notieren.
3. Unter HAOS zuerst den [Binärbau- und Lieferweg](haos-installation.md) abschließen.
   Ein normaler HACS-Download löst einen fehlenden Musl-Wheel nicht.

## 3. Über HACS installieren

1. In HACS **Benutzerdefinierte Repositories** öffnen.
2. `https://github.com/togo42/Adaptive-Solar` als Typ **Integration** hinzufügen.
3. Eine veröffentlichte Version auswählen und herunterladen.
4. Home Assistant neu starten; anschließend die Protokolle auf Fehler zu
   `adaptive_solar`, `pvlib` und `sklearn` prüfen.
5. **Einstellungen → Geräte & Dienste → Integration hinzufügen → Adaptive Solar**
   öffnen. Standort, Ausgangsstufen und Strings gemäß [Bedienung](bedienung.md)
   einrichten. Bestehende Einträge werden beim Upgrade weiterverwendet.

HACS selbst wird nach seiner [offiziellen Anleitung](https://www.hacs.xyz/docs/use/)
installiert. Projektcode und Abhängigkeiten bleiben unterschiedliche Lieferteile.

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
- HA-Konfigurationsprüfung und Reparaturen auf neue Probleme prüfen. Für die eigene
  Installation verbleibt die Qualifikation der Messquellen und später des Lernens.

Fehlender Wetterzugang oder unpassende Binärabhängigkeiten können bereits das Setup
verhindern. Diagnosepfade: [Fehlerbehebung](bedienung.md#7-fehlerbehebung-und-support).

## 6. Aktualisieren, zurückkehren und entfernen

Vor Updates die Versionshinweise lesen, sichern und verwendete Geräte-/Sensorverweise
notieren. Für 0.2.10 erklärt [die Releasebeschreibung](release-0.2.10.md) die
Anzeige-Migration und den Featurevertragswechsel. HACS aktualisiert den Code;
anschließend Core neu starten und obige Prüfung wiederholen. Änderungen an Physik
oder Messbindungen können neue Lernhistorie erfordern. Das Optionsformular lädt
den Eintrag nach Abschluss neu.

Bei Problemen den Eintrag zunächst deaktivieren und die Diagnose sichern. HACS kann
eine verfügbare ältere Version erneut herunterladen; manuell den gesamten gesicherten
Komponentenordner zurückspielen. Eine ältere Version kann neuere Historien nicht
zwingend lesen. Deshalb vorab Daten sichern und eine Code-Rückkehr nicht als
garantierte Rückmigration der Historie behandeln. Abhängigkeiten nur anhand des
Zielmanifests und des gesicherten Paketstands zurücksetzen, keine fremden Pakete löschen.

Zum Entfernen zuerst abhängige Automationen, Dashboards und Energy-Verknüpfungen
prüfen, dann den Eintrag in Geräte & Dienste entfernen und bei Bedarf den Code in
HACS deinstallieren. **Eintragslöschung ist kein nachgewiesener Datenlöschvorgang**:
Lernstores, Recorder und Sicherungen können Daten behalten. Den Umfang einer
vollständigen Löschung beschreibt [Datenschutz](datenschutz.md#4-entfernen-und-aufbewahrung).
