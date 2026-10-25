# Adaptive Solar für Home Assistant

<p align="center">
  <img src="assets/adaptive-solar-logo.png" alt="Adaptive Solar: Sonne über einem Solarmodul mit aufsteigender Prognosekurve" width="240">
</p>

[GitHub](https://github.com/togo42/Adaptive-Solar) · [Fehler melden](https://github.com/togo42/Adaptive-Solar/issues) · [Logo und Gestaltung](docs/branding.md)

Wetterprognosen, PV-Physik und lokale Residualmodelle für Resttag und nächste sieben Tage: unterschiedliche Stringausrichtungen, gemeinsame AC-/DC-Ausgabestufen und wiederkehrende Verschattung. Frische HA-Temperatur/Windwerte, optional Ecowitt-Globalstrahlung und geeignete PV-Leistung unterstützen den kurzfristigen Nowcast.

**Stand, 25.10.2026:** **0.2.9 installiert**, vier Anlageneinträge liefern unter Core **2026.10.4** Prognosen. Die freigegebenen Lern-/Leistungsbindungen und optionalen Messgültigkeitsquellen sind aktiviert und zurückgelesen; erste originale Messintervalle werden angenommen. Je **852 Tests** mit Core 2026.10.2, .3 und .4 bestanden. Der gebundene Implementierungsreview durch **Grok 4.7/high** ist ohne Findings abgeschlossen ([Reviewumfang](docs/review-findings.md)). Ein qualifizierter produktiver ML-Fit und Überlegenheit gegenüber Helios und Open-Meteo Solar sind weiterhin offen. [Prüfstand](docs/entwicklungsstand.md), [Reviewnachweise](docs/review-findings.md), [Validierungsplan](docs/validierung.md).

## Funktionsweise

Open-Meteo liefert verfügbare Modellintervalle. pvlib berechnet Sonnenstand, Transposition und Temperaturverluste je String; Stringsumme und Begrenzung erfolgen gemeinsam je deklarierter AC-/DC-Stufe. DC hat keine versteckte AC-Effizienz. Optionale Horizonte dämpfen direkte Strahlung teilweise.

Gradient Boosting lernt je Stufe und NWP-/GHI-Regime auf prospektiv archivierten Features und späteren Messintervallen. Training, Prüfung und Kalibrierung liegen zeitlich getrennt; unbelegte Lead-Bereiche behalten Physik. Ohne qualifizierte Historie bleibt das Modell kalt. Ein gemeinsamer Zähler identifiziert keine Einzelstringverluste.

Ausgegeben wird **verfügbares PV-Potenzial ohne betriebliche Abregelung**, keine Reglerbefehlsprognose. Abregelung, Eingabeprobleme, Resttagslücken und Physik-/teilweise/vollständige Residualanwendung sind getrennte Qualitätszustände, keine Genauigkeitsklassen. Alle Näherungen, Datenverträge und APIparameter: [Implementierungsvertrag](docs/implementation-contract.md).

Herstellerunabhängige String-/Stufenkonfiguration, optionale HA-Sensoren: keine Pflicht für Wechselrichtermarke, Batterietyp oder Hersteller-API. Ohne Abregelungssignal gilt die zu prüfende Annahme ungedrosselten Betriebs. Ein voller Akku allein beweist keine Abregelung; Genauigkeit auf beliebiger Hardware ist nicht belegt.

## Einrichtung

Geprüfte HA-Ziele **2026.10.2/.3/.4** mit Python 3.14; der HA-unabhängige Modellkern unterstützt Python ab 3.13. `custom_components/adaptive_solar` in die HA-Konfiguration kopieren. **HAOS/amd64:** [Musl-Bauweg](docs/haos-installation.md) für `scikit-learn==1.9.1` beachten.

Nach Neustart: **Einstellungen → Geräte & Dienste → Integration hinzufügen → Adaptive Solar**. Einrichtung, Prognoseausgabe, Persistenz und Optionsänderung sind live geprüft; produktives Training mit qualifizierter Messhistorie steht noch aus.

Je String kWp, Neigung, Azimut und Verluste: **0°N/90°O/180°S/270°W**. AC: Wirkungsgrad/AC-Grenze; DC: nominelle Ausgangsgrenze/optionaler Zusatzverlust, keine spannungsunabhängige Hardwaregarantie. Fiktive [AC-](examples/site.json)/[DC-Beispiele](examples/site-dc.json); Details im Implementierungsvertrag.

Lernen braucht kumulative PV-Energie am richtigen Messpunkt, Nowcast Leistung in W. Keine Zählermehrfachbindung an unabhängige Stufen; Netzbilanz/Batterieentladung sind keine PV-Produktion. Mindestens95% Messabdeckung/höchstens2,5% Randlücke; `training_quality` erklärt Ablehnungen. Energieintegrale, Verfügbarkeit und Abregelung separat qualifizieren; HA-Empfang allein genügt nicht.

Optional kann je Stufe ein [Messgültigkeitssignal](docs/measurement-validity.md) ungültige Energie- und Leistungsdaten sperren. Es ersetzt kein Abregelungssignal. Bei aus mehreren Leistungen berechneter Energie muss der externe Qualitätsadapter alle benötigten Originalquellen prüfen; ursprüngliche Zähler und echte Nullberichte bleiben erhalten.

Optionales GHI verlangt echte horizontale W/m², Frische und geeigneten Sonnenstand. Lücken bleiben fehlend; Modelle entstehen aus lokalen Zeilen, nicht ausführbaren Dateien.

Resttag enthält die verbleibende Teilstunde; native Energy nur volle UTC-Stunden homogener Entries. Tagesbeginnprognose braucht einen vor Mitternacht eingefrorenen Snapshot.

## Entwicklung

```bash
python3.14 -m venv .venv
.venv/bin/python -m pip install '.[test,ha-test]'
.venv/bin/python -m pytest
.venv/bin/ruff check custom_components tests scripts
```

Prüfversionen, Abhängigkeitspins und Nachweisgrenzen: [Entwicklungsstand](docs/entwicklungsstand.md).

Synthetische Offline-Demo; für DC `--config examples/site-dc.json` einsetzen:

```bash
.venv/bin/python scripts/forecast.py --config examples/site.json --synthetic \
    --as-of 2026-06-21T08:00:00+02:00 --output artifacts/demo.json
```

`--live` ruft Open-Meteo auf und ist nicht rückdatierbar. Reale Prognosen/Recorder-Istwerte archivieren und vergleichen: [Aufnahmeleitfaden](docs/benchmark-aufnahme.md). Private Zuordnungen unter ignoriertem `data/`; Standorte, Entity-IDs und Zugangsdaten weder in Git noch Reviews.

## Recherche und Quellen

Grundlagen: [Ensembles](ensemble_hybrid_solar_forecasting.md), [ML](solar_ml_research.md), [Daten/Merkmale](solarprognose_datenquellen_feature_engineering.md), [Gesamtrecherche](solar-prognose-ml-recherche.md). Literaturmetriken anderer Datensätze sind keine erwarteten lokalen Ergebnisse. Referenzen: [Helios Forecast](https://github.com/ReikanYsora/Helios-Forecast), [Open-Meteo Solar Forecast](https://github.com/rany2/open-meteo-solar-forecast); kein übernommener Quellcode.

Primärquellen/Parameter: [Implementierungsvertrag](docs/implementation-contract.md); [Open-Meteo API](https://open-meteo.com/en/docs), [pvlib](https://pvlib-python.readthedocs.io/), [scikit-learn](https://scikit-learn.org/stable/), [HA](https://developers.home-assistant.io/).

Open-Meteos freie API erlaubt private Hausautomation gemäß nichtkommerziellen [Nutzungsbedingungen](https://open-meteo.com/en/terms); Attribution/Limits gelten. Bibliothekslizenzen und API-Bedingungen sind getrennt zu betrachten.
