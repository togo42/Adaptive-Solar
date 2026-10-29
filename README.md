# Adaptive Solar für Home Assistant

<p align="center">
  <img src="assets/adaptive-solar-logo.png" alt="Adaptive Solar: Sonne über einem Solarmodul mit aufsteigender Prognosekurve" width="240">
</p>

[GitHub](https://github.com/togo42/Adaptive-Solar) · [Fehler melden](https://github.com/togo42/Adaptive-Solar/issues) · [Logo und Gestaltung](docs/branding.md)

Wetterprognosen, PV-Physik und lokale Residualmodelle für bis zu sieben lokale Kalendertage einschließlich heute: Resttag und bis zu sechs Folgetage, abhängig von der Wetterabdeckung. Unterschiedliche Stringausrichtungen, gemeinsame AC-/DC-Ausgabestufen und wiederkehrende Verschattung werden berücksichtigt. Frische HA-Temperatur/Windwerte, optionale horizontale Globalstrahlung und geeignete PV-Leistung unterstützen den kurzfristigen Nowcast.

**Stand, 28.10.2026:** **0.2.17 veröffentlicht und auf HA sowie dem Archivhost installiert.** 1.634 Tests ohne Skips, 90,84 % kombinierte Abdeckung und erfolgreiche Main-/Tag-CI. Vier aktive Exporte und Hosttimer, vier Originalreplays, acht Schattenreplays sowie eine Archivwiederherstellung sind geprüft; Konfiguration und Historie sind erhalten. 0.2.17 korrigiert den Vergleich kleinster Rundungsunterschiede beim Original-/Schattenreplay. [Release und Upgrade](docs/release-0.2.17.md), [Betriebs- und Prüfstand](docs/entwicklungsstand.md), [Validierungsplan](docs/validierung.md).

**Archivhost ohne lokales HA, installiert am 29.10.2026:** [Installation und Updates](docs/archiv-runtime-ohne-ha.md) verwenden einen eigenen Installer mit verpflichtender HA-Paketsperre. Historische Replayabnahmen behalten ihre strenge Versionsprüfung.

**Archivhost-Erweiterung nach 0.2.17 installiert:** Die [hierarchische Hashablage](docs/archiv-hashablage.md) verteilt Originalpakete auf Präfixverzeichnisse. Migration und Rückweg bewahren Bytes, Pins und Checkpoints; ältere Replayumgebungen erhalten flache Datasetkopien. Der Installationsnachweis steht im verlinkten Betriebsbericht.

**Messdatenänderungen in 0.2.13:** Die [Messaufbereitung](docs/messintervalle-92-prozent.md) behandelt kurze Rundungsbursts, wählt den längsten gültigen Messblock und verlangt nun 92 % Abdeckung mit höchstens drei Minuten Lücke je Rand. Veröffentlichung und Installation sind gegenüber dem bisherigen 0.2.12-Stand getrennt nachgewiesen.

**Neu in 0.2.15:** [Messkontinuität und echte Endpunktfenster](docs/measurement-learning.md) ergänzen die bisherigen Qualitätsgates. Ein kleiner [früher Bias-Kandidat](docs/early-bias-shadow.md) läuft ausschließlich im Shadow-Betrieb. [Physik-, Schatten- und Nowcastoptionen](docs/physics-learning-options.md), [Wetter-/Lernfehler und Ressourcen](docs/forecast-resilience.md) sowie ein [getrenntes Modellvergleichsarchiv](docs/model-comparison-archive.md) machen Kandidaten überprüfbar. Die Änderungen sind kein Nachweis besserer realer Prognosen; dafür bleibt ein prospektiver Anlagenvergleich erforderlich.

Die [Ablehnungsdiagnose](docs/ablehnungsdiagnose.md) ergänzt eindeutige Ziel-/Zeilendetails mit Originalzeiten und Gründen (`schema_version: 1`, höchstens 50 Einträge je Gruppe). Zielzähler und Details zeigen gemeinsam den letzten tatsächlichen Fit-Cutoff; Cachehits erfinden keine neue Auswertung. Der tatsächliche Installationsstand steht im Prüfstand.

## Funktionsweise

Open-Meteo liefert verfügbare Modellintervalle. pvlib berechnet Sonnenstand, Transposition und Temperaturverluste je String; Stringsumme und Begrenzung erfolgen gemeinsam je deklarierter AC-/DC-Stufe. DC hat keine versteckte AC-Effizienz. Optionale Horizonte dämpfen direkte Strahlung teilweise.

Gradient Boosting lernt je Stufe und NWP-/GHI-Regime auf prospektiv archivierten Features und späteren Messintervallen. Training, Prüfung und Kalibrierung liegen zeitlich getrennt; unbelegte Lead-Bereiche behalten Physik. Ohne qualifizierte Historie bleibt das Modell kalt. Ein gemeinsamer Zähler identifiziert keine Einzelstringverluste.

Ausgegeben wird **verfügbares PV-Potenzial ohne betriebliche Abregelung**, keine Reglerbefehlsprognose. Abregelung, Eingabeprobleme, Resttagslücken und Physik-/teilweise/vollständige Residualanwendung sind getrennte Qualitätszustände, keine Genauigkeitsklassen. Alle Näherungen, Datenverträge und APIparameter: [Implementierungsvertrag](docs/implementation-contract.md).

Herstellerunabhängige String-/Stufenkonfiguration, optionale HA-Sensoren: keine Pflicht für Wechselrichtermarke, Batterietyp oder Hersteller-API. Ohne Abregelungssignal gilt die zu prüfende Annahme ungedrosselten Betriebs. Ein voller Akku allein beweist keine Abregelung; Genauigkeit auf beliebiger Hardware ist nicht belegt.

## Installation und Bedienung

| Anleitung | Inhalt |
| --- | --- |
| [Installation](docs/installation.md) | Geprüfte Plattformen, HACS, manuelle Installation, Upgrade und Rückweg |
| [HAOS-Binärabhängigkeiten](docs/haos-installation.md) | amd64-Musl-Wheel bauen, vorbereiten und im persistenten Corepfad bereitstellen |
| [Bedienung](docs/bedienung.md) | Alle Einrichtungsfelder, Sensoren, Energy, Lernstatus und Fehlerbehebung |
| [Datenschutz](docs/datenschutz.md) | Externe Datenflüsse, lokale Speicherung und Diagnoseweitergabe |

HACS-Mindestversion ist **Core 2026.10.2**. Historische Kompatibilitätsprüfungen betreffen **2026.10.2/.3/.4** mit Python 3.14; die vollständige Suite für **0.2.17** läuft auf **2026.10.4**. Andere Versionen sind damit nicht automatisch neu geprüft. **HAOS ist bislang nur auf amd64 mit passender CPython-3.14-Musl-Binärbasis belegt.** ARM/Raspberry Pi und andere Python-ABIs sind nicht qualifiziert. Der HA-unabhängige Modellkern unterstützt Python ab 3.13.

Über HACS: **Benutzerdefinierte Repositories** öffnen, `https://github.com/togo42/Adaptive-Solar` als **Integration** hinzufügen und die gewünschte veröffentlichte Version herunterladen. Danach Home Assistant neu starten und **Adaptive Solar** unter **Einstellungen → Geräte & Dienste** hinzufügen beziehungsweise bestehende Einträge weiterverwenden. [Änderungen und Upgrade in 0.2.17](docs/release-0.2.17.md). Die benötigte HAOS-Binärbasis ist unten separat beschrieben; HACS ersetzt diese Abhängigkeit nicht.

Alternativ den vollständigen Ordner `custom_components/adaptive_solar` in das gleichnamige Verzeichnis der HA-Konfiguration kopieren; Details und Abhängigkeitsprüfung stehen in der Installationsanleitung.

Nach Neustart: **Einstellungen → Geräte & Dienste → Integration hinzufügen → Adaptive Solar**. Einrichtung, Prognoseausgabe, Persistenz und Optionsänderung sind live geprüft; produktives Training mit qualifizierter Messhistorie steht noch aus.

Je String kWp, Neigung, Azimut und Verluste: **0°N/90°O/180°S/270°W**. AC: Wirkungsgrad/AC-Grenze; DC: nominelle Ausgangsgrenze/optionaler Zusatzverlust, keine spannungsunabhängige Hardwaregarantie. Fiktive [AC-](examples/site.json)/[DC-Beispiele](examples/site-dc.json); Details im Implementierungsvertrag.

Optional lassen sich je String Horizontpunkte sowie Morgen-/Abenddämpfungen von 0 bis 1 eintragen. 0 bedeutet keine Dämpfung; zwischen Sonnenaufgang, Tageslichtmitte und Sonnenuntergang wird linear überblendet. Vorhandene Dämpfungen anderer Prognoseintegrationen können als Ausgangswerte dienen, müssen aber dieselbe Solarfläche beschreiben. Die Horizontkorrektur lässt diffuse Strahlung erhalten. Bei einer Ausgangsstufe erscheint nur ihr Gerätebereich; vorhandene alte Gesamt-Sensoren bleiben ausgeblendet für bestehende Verweise verfügbar.

Lernen braucht kumulative PV-Energie am richtigen Messpunkt, Nowcast Leistung in W. Keine Zählermehrfachbindung an unabhängige Stufen; Netzbilanz/Batterieentladung sind keine PV-Produktion. Mindestens 92 % Messabdeckung und höchstens drei Minuten Lücke je Rand; `training_quality` erklärt Ablehnungen. Energieintegrale, Verfügbarkeit und Abregelung separat qualifizieren; HA-Empfang allein genügt nicht.

Optional kann je Stufe ein [Messgültigkeitssignal](docs/measurement-validity.md) ungültige Energie- und Leistungsdaten sperren. Es ersetzt kein Abregelungssignal. Bei aus mehreren Leistungen berechneter Energie muss der externe Qualitätsadapter alle benötigten Originalquellen prüfen; ursprüngliche Zähler und echte Nullberichte bleiben erhalten.

Optionales GHI verlangt echte horizontale W/m², Frische und geeigneten Sonnenstand. Lücken bleiben fehlend; Modelle entstehen aus lokalen Zeilen, nicht ausführbaren Dateien.

Resttag enthält die verbleibende Teilstunde; native Energy nur volle UTC-Stunden homogener Entries. Tagesbeginnprognose braucht einen vor Mitternacht eingefrorenen Snapshot. Historische Werte bleiben seit 0.2.14 mit Originalkonfiguration gekennzeichnet erhalten; [Wiederherstellung verlorener Originalwerte](docs/forecast-repairs.md#3-bereits-verlorenen-originalwert-gezielt-wiederherstellen).

## Entwicklung

```bash
python3.14 -m venv .venv
.venv/bin/python -m pip install '.[test,ha-test]'
.venv/bin/python -m pip install 'pvlib==0.16.1' 'scikit-learn==1.9.1'
.venv/bin/python -m pip check
.venv/bin/python -m pytest -q --cov=custom_components.adaptive_solar --cov-branch \
    --cov-report=term-missing:skip-covered --cov-report=xml:artifacts/coverage.xml
.venv/bin/ruff check custom_components tests scripts
```

Die zweite Installation gleicht die Laufzeitbibliotheken mit dem aktuellen HA-Manifest ab, wie es auch CI tut. Der [Entwicklungsleitfaden](docs/entwicklung.md) zeigt die automatische Übernahme dieser Pins, die Testmatrix und den Ablauf für Beiträge. Historische Nachweise: [Entwicklungsstand](docs/entwicklungsstand.md).

Synthetische Offline-Demo; für DC `--config examples/site-dc.json` einsetzen:

```bash
.venv/bin/python scripts/forecast.py --config examples/site.json --synthetic \
    --as-of 2026-06-21T08:00:00+02:00 --output artifacts/demo.json
```

`--live` ruft Open-Meteo auf und ist nicht rückdatierbar. Reale Prognosen/Recorder-Istwerte archivieren und vergleichen: [Aufnahmeleitfaden](docs/benchmark-aufnahme.md). Private Zuordnungen unter ignoriertem `data/`; Standorte, Entity-IDs und Zugangsdaten weder in Git noch Reviews.

**Originaldatenarchiv ab 0.2.16:** Optionaler HA-Export, externes Archiv mit 24 Monaten Aufbewahrung, zusätzliche Wetter-/Ensembleaufnahmen und Offline-Replay. Die [Betriebsanleitung](docs/archivbetrieb.md) beschreibt Aufnahme, eingefrorene Datensätze und Grenzen; die [Hostinstallation](docs/archiv-host-installation.md) Dienste, verschlüsselte Zugangsdaten und Speichergrenzen. Originaldateien bleiben maßgeblich, SQLite ist der lokale Index; PostgreSQL kann später als Abfrageebene ergänzt werden.

Die [Wettermodellrecherche für die nächsten 24/48 Stunden](docs/wettermodelle-und-prognosehorizonte.md) begründet regionale Kurzfristmodelle, länger verfügbare Vergleichsmodelle und echte Wetterensembles. Der Offline-Pfad berechnet Energiequantile und Schwellenanteile aus vollständigen Mitgliedsverläufen; ihre lokale Zuverlässigkeit ist noch nicht gemessen. Speicherbewertungen sind nach drei und sechs Monaten vorgesehen. Neue produktive Modellgewichte und Akkuaktionen stehen weiterhin aus. Die seit 0.2.15 optionalen [Physikvarianten mit Zeitintegration und IAM](docs/physics-learning-options.md) müssen anhand der Originaldaten lokal verglichen werden.

Der Archivzweig erfasst auch ungültige Originalbeobachtungen und sämtliche
Schattenlernversuche. Ein [chronologischer Schatten-Replay](docs/archivbetrieb.md#51-schattenlernen-chronologisch-vergleichen)
vergleicht unabhängige Lernverläufe auf denselben früher verfügbaren Eingaben.
Als [Speicherung](docs/archiv-speicherung-und-transport.md) bleiben zunächst
Originaldateien und SQLite vorgesehen; PostgreSQL ist eine spätere Ausbauoption.

## Recherche und Quellen

Grundlagen: [Ensembles](ensemble_hybrid_solar_forecasting.md), [ML](solar_ml_research.md), [Daten/Merkmale](solarprognose_datenquellen_feature_engineering.md), [Gesamtrecherche](solar-prognose-ml-recherche.md). Literaturmetriken anderer Datensätze sind keine erwarteten lokalen Ergebnisse. Referenzen: [Helios Forecast](https://github.com/ReikanYsora/Helios-Forecast), [Open-Meteo Solar Forecast](https://github.com/rany2/open-meteo-solar-forecast); kein übernommener Quellcode.

Primärquellen/Parameter: [Implementierungsvertrag](docs/implementation-contract.md); [Open-Meteo API](https://open-meteo.com/en/docs), [pvlib](https://pvlib-python.readthedocs.io/), [scikit-learn](https://scikit-learn.org/stable/), [HA](https://developers.home-assistant.io/).

Open-Meteos freie API erlaubt private Hausautomation gemäß nichtkommerziellen [Nutzungsbedingungen](https://open-meteo.com/en/terms); Attribution/Limits gelten. Bibliothekslizenzen und API-Bedingungen sind getrennt zu betrachten.

## Lizenz

Copyright (C) 2026 Torsten Godau.

Die eigenen Inhalte dieses Repositories, einschließlich Quellcode, Tests, Beispielen,
Dokumentation und Projektgrafiken, stehen, soweit urheberrechtlich geschützt, unter
der **GNU General Public License, ausschließlich Version 3** (`GPL-3.0-only`).
Der vollständige unveränderte Lizenztext steht in [LICENSE](LICENSE); eine identische
Kopie wird für HACS innerhalb der Integration mitgeliefert.

Private und kommerzielle Nutzung sind erlaubt. Wer vom Copyleft erfasste geänderte
Versionen weitergibt, muss sie ebenfalls unter GPL Version 3 bereitstellen und den
Empfängern den zugehörigen Quellcode gemäß den Lizenzbedingungen zugänglich machen.
Rein private Änderungen müssen nicht veröffentlicht werden. Die Software wird ohne
Gewährleistung im Umfang der Lizenz bereitgestellt.

Externe Bibliotheken und zitierte fremde Inhalte behalten ihre jeweiligen Lizenzen;
die Bedingungen und Attributionspflichten der Wetterdienste gelten zusätzlich.
Die Projektlizenz erlaubt keine kommerzielle Nutzung von Open-Meteos freier API
entgegen deren Nutzungsbedingungen. Hinweise zur Verwendung des Projektlogos:
[Logo und Gestaltung](docs/branding.md).
