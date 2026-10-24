# Frei nutzbare Solar-Prognosemodelle und Tools für private Anwendungen

> Stand: Oktober 2026 | Recherche: frei nutzbar = kostenlos, open source oder mit kostenlosem Tier für private Nutzung

---

## Inhaltsverzeichnis

1. [Open-Meteo (Weather & Solar Forecast API)](#1-open-meteo-weather--solar-forecast-api)
2. [Forecast.Solar](#2-forecastsolar)
3. [pvlib-python](#3-pvlib-python)
4. [Solcast (Free Tier)](#4-solcast-free-tier)
5. [OpenWeatherMap](#5-openweathermap)
6. [Open-Source Solar-Forecast-Projekte auf GitHub](#6-open-source-solar-forecast-projekte-auf-github)
7. [Home Assistant Integrationen](#7-home-assistant-integrationen-für-solar-prognose)
8. [Vergleichstabelle](#8-vergleichstabelle)
9. [Empfehlungen](#9-empfehlungen)

---

## 1. Open-Meteo (Weather & Solar Forecast API)

### Beschreibung

Open-Meteo ist eine Open-Source-Weather-API (AGPLv3), die kostenlosen Zugang für nicht-kommerzielle Nutzung bietet. Die API liefert Wettervorhersagen aus über 15 nationalen Wetterdiensten (ECMWF, DWD, NOAA, Météo-France, JMA, KMA, KNMI, DMI, MeteoSwiss, UK Met Office, BOM, CMA, GeoSphere Austria). Die Daten sind unter CC BY 4.0 lizenziert (auch kommerziell nutzbar mit Attribution).

Für Solaranwendungen bietet Open-Meteo mehrere relevante Endpunkte:

- **Weather Forecast API**: Stündliche Vorhersagen mit Solarstrahlungsvariablen:
  - `shortwave_radiation` (GHI — Global Horizontal Irradiance)
  - `direct_radiation` (Direktstrahlung)
  - `diffuse_radiation` (Diffusstrahlung)
  - `direct_normal_irradiance` (DNI)
  - `global_tilted_irradiance` (GTI — für geneigte Module)
  - `terrestrial_radiation` (TOA-Strahlung)
  - `shortwave_radiation_clear_sky` (Clear-Sky-Strahlung)
  - Plus: Temperatur, Windgeschwindigkeit, Bewölkung, Niederschlag etc.

- **Satellite Radiation API**: Echtzeit-Solarstrahlung aus Satellitendaten (EUMETSAT MSG/MTG, Himawari-9, SARAH3). Räumliche Auflösung 2,5–5 km, zeitliche Auflösung 10–30 Minuten. Verfügbar für Europa, Afrika, Asien, Australien.

- **Historical Weather API**: ERA5-Reanalysis (1940–heute), gap-free global grid. Für Bias-Korrektur und ML-Training.

- **Historical Forecast Archive**: Seit 2021, gleiche Format wie Live-API. Für Bias-Korrektur und Post-Processing.

### Modelltyp

- **Deterministische NWP-Modelle** (keine ML-Modellierung der PV-Leistung, sondern Strahlungsprognosen)
- Der Benutzer berechnet die PV-Leistung selbst (z. B. mit pvlib) aus den Strahlungs- und Wetterdaten
- Auflösung: 1–2 km (regional) bis 9–11 km (global)
- Update-Frequenz: 6 h (global), 1–3 h (regional, z. B. ICON-D2, HRRR, AROME)
- Vorhersagehorizont: Bis zu 16 Tage (je nach Modell)
- 15-minütige Daten für Zentraleuropa und Nordamerika

### Genauigkeit

- Nicht direkt angegeben (Open-Meteo ist ein Datenprovider, kein PV-Leistungsmodell)
- Die Genauigkeit hängt vom gewählten Wettermodell ab
- Historische Forecast-Archive ermöglichen Bias-Korrektur und Skill-Analyse
- Previous Runs API für lead-time-stratifizierte Skill-Analyse

### Kosten/Lizenz

- **Kostenlos** für nicht-kommerzielle Nutzung (bis 10.000 API-Calls/Tag)
- Kein API-Key, keine Registrierung erforderlich
- Kommerzielle Nutzung: Subscription-Pläne (rate-limit-Erhöhung, Priority-Support)
- Daten: CC BY 4.0 (frei nutzbar und weiterverbreitbar, mit Attribution)
- Server-Code: AGPLv3 (Self-Hosting für unbegrenzte Calls möglich)
- Self-Hosting: Für High-Volume-ML-Workloads oder air-gapped-Umgebungen

### Links

- Website: https://open-meteo.com
- API-Dokumentation: https://open-meteo.com/en/docs
- Satellite Radiation API: https://open-meteo.com/en/docs/satellite-radiation-api
- GitHub: https://github.com/open-meteo/open-meteo
- Python-Modul (Solar): https://github.com/rany2/open-meteo-solar-forecast

---

## 2. Forecast.Solar

### Beschreibung

Forecast.Solar ist ein RESTful API-Dienst für Solarproduktions- und Wettervorhersagedaten. Die Prognose basiert auf der Kombination von:

- Historischen Bestrahlungsdaten aus **PVGIS** (Photovoltaic Geographical Information System, JRC der EU-Kommission)
- Historischen Wetterdaten
- Aktuellen Wettervorhersagedaten aus verschiedenen Diensten (Wunderground, OpenWeatherMap, AerisWeather, DWD, Norwegian Met Institute)

Die Forecast.Solar-Integration ist in Home Assistant standardmäßig verfügbar (eingebaut).

### Modelltyp

- **Empirisches/statistisches Modell** (kein reines ML-Modell)
- Nutzt historische Bestrahlungsdaten (PVGIS) + Cloud-Coverage-Prognosen
- Berücksichtigt Standort (Lat/Lon), Neigung, Azimut
- Dämpfungsfaktor (Damping) für Realitätsnähe
- Anpassung durch tatsächliche Messwerte möglich (Adjust Forecast)
- Vorhersagehorizont: Bis zu 7 Tage (je nach Account-Modell)

### Genauigkeit

- Keine publizierten MAE/RMSE-Werte in der Dokumentation
- Community-Berichte: Oft als "weniger genau" als Solcast und Open-Meteo-basierte Lösungen wahrgenommen
- HA-Community-Forum: Nutzer berichten von signifikanten Abweichungen, insbesondere bei bewölktem Wetter
- Vorteil: Kostenlos verfügbar, keine API-Key-Registrierung für "Public"-Tier

### Kosten/Lizenz

- **"Public"-Tier**: Kostenlos, ohne API-Key (rate-limited)
- **"Personal"-Tier und höher**: Kostenpflichtig (PayPal-Subscription)
- Rate-Limiting: 429-Fehler bei Überschreitung (siehe HA-Issue #91225)
- API-Dokumentation: https://doc.forecast.solar
- Datenquellen: PVGIS (EU-Kommission), Wunderground, OpenWeatherMap, AerisWeather, DWD, MET Norway

### Links

- Website: https://forecast.solar
- API-Dokumentation: https://doc.forecast.solar
- Account-Modelle: https://doc.forecast.solar/account_models
- HA-Integration: https://www.home-assistant.io/integrations/forecast_solar/
- Python-Modul: https://pypi.org/project/forecast-solar/

---

## 3. pvlib-python

### Beschreibung

pvlib-python ist eine Community-entwickelte Python-Toolbox für die Simulation von Photovoltaik-Energiesystemen. Sie bietet Funktionen und Klassen für:

- Solare Positionsberechnung
- Clear-Sky-Modelle
- PV-System-Modellierung (Modul, Inverter, Array)
- **Wettervorhersage-Integration** (NOAA GFS, NAM, RAP, HRRR)
- PV-Leistungsprognosen aus Wettervorhersagen

pvlib ist kein eigenständiges Prognosemodell, sondern ein **Framework**, mit dem man eigene Prognosepipelines bauen kann. Es kann mit beliebigen Wetterdaten (Open-Meteo, NOAA, ECMWF) kombiniert werden.

### Modelltyp

- **Physikalisches Modell** (strahlungsbasiert)
- Pipeline: Wettervorhersage → Solarposition → Bestrahlung auf Modulebene (POA) → PV-Leistung
- Unterstützt verschiedene Modul-/Inverter-Modelle (SAPM, PVWatts, etc.)
- Kann mit ML-Modellen kombiniert werden (pvlib + XGBoost etc.)

### Genauigkeit

- Abhängig von der Qualität der Wettervorhersage und der PV-System-Parametrisierung
- Typische Genauigkeit: MAE 10–20% der Nennleistung (für gut parametrisierte Systeme)
- pvlib selbst ist ein Simulationsframework — die Genauigkeit hängt von der Eingabe ab
- IEEE-Paper: "A Comparison of PV Power Forecasts Using PVLib-Python" (2018)

### Kosten/Lizenz

- **Open Source** (BSD-3-Clause)
- Kostenlos nutzbar, auch kommerziell
- Python-Paket: `pip install pvlib`
- Dokumentation: https://pvlib-python.readthedocs.io

### Links

- Dokumentation: https://pvlib-python.readthedocs.io
- GitHub: https://github.com/pvlib/pvlib-python
- Forecasting-Guide: https://pvlib-python.readthedocs.io/en/stable/user_guide/forecasting.html
- IEEE-Paper: https://ieeexplore.ieee.org/document/8366724/

---

## 4. Solcast (Free Tier)

### Beschreibung

Solcast ist ein kommerzieller Solar-Datenanbieter, der hochauflösende Solarstrahlungs- und PV-Leistungsprognosen liefert. Die Daten basieren auf Satellitenbildern und NWP-Modellen.

Für private Nutzer bietet Solcast einen **kostenlosen Tier** an:
- Bis zu 10 API-Anfragen pro Tag
- Erfordert Verifizierung, dass die Location eine Wohnadresse ist
- Liefert Strahlungs- (GHI, DNI, DHI) und Wetterdaten sowie PV-Leistungsprognosen

### Modelltyp

- **Satellitenbasiert + NWP** (proprietär)
- Nutzt geostationäre Satellitenbilder (real-time cloud tracking)
- Kombiniert mit NWP-Modellen
- Liefert PV-Leistungsprognosen direkt (nicht nur Strahlung)

### Genauigkeit

- Solcast wird in der Community als **sehr genau** wahrgenommen
- HA-Community: "Solcast ist reporting 8kWh" (realistischere Werte als Forecast.Solar)
- Bankable Datenqualität (für kommerzielle Projekte)
- Keine publizierten MAE/RMSE für den Free Tier
- Reddit-Community: Solcast gilt als Referenzstandard unter den kostenlosen Optionen

### Kosten/Lizenz

- **Free Tier**: 10 API-Calls/Tag (für verifizierte Wohnadressen)
- **Kostenpflichtig**: Enterprise-Pläne für höhere Volumina
- API-Dokumentation: https://docs.solcast.com.au
- Home Assistant Integration: Custom Component (HACS)

### Links

- Website: https://solcast.com/free-rooftop-solar-forecasting
- API-Dokumentation: https://docs.solcast.com.au
- Pricing: https://solcast.com/pricing/energy-data
- HA-Community: https://community.home-assistant.io/t/solcast-global-solar-power-forecast-integration/

---

## 5. OpenWeatherMap

### Beschreibung

OpenWeatherMap bietet eine kostenlose Wetter-API (1.000 Calls/Tag im Free Tier). Es gibt **keine dedizierte Solar-Irradiance-API** im kostenlosen Tier. Die Solar-Irradiance-API ist ein kostenpflichtiges Premium-Feature.

Im Free Tier sind folgende Daten verfügbar:
- Aktuelles Wetter (Temperatur, Bewölkung, Wind, etc.)
- 5-Tage-Vorhersage (3-stündlich)
- **Keine** Solarstrahlungsdaten (GHI, DNI, etc.) im kostenlosen Tier

### Modelltyp

- Wettervorhersage-Modell (kein PV-Leistungsmodell)
- Keine Solarstrahlungsdaten im Free Tier

### Genauigkeit

- Nicht relevant für Solar-Prognose (keine Strahlungsdaten im Free Tier)

### Kosten/Lizenz

- **Free Tier**: 1.000 Calls/Tag (Wetterdaten, keine Solarstrahlung)
- **Solar Irradiance API**: Kostenpflichtig (Premium)
- API-Key erforderlich (Registrierung nötig, Kreditkarte bei Aktivierung)
- Ersatz durch Open-Meteo empfohlen (kostenlos, mehr Daten)

### Links

- Website: https://openweathermap.org
- Pricing: https://openweathermap.org/price
- Solar Irradiance API: https://openweathermap.org/api/solar-irradiance

---

## 6. Open-Source Solar-Forecast-Projekte auf GitHub

### 6.1 Open-Source Quartz Solar Forecast (Open Climate Fix)

**Beschreibung:** Open-Source PV-Prognose auf Site-Level. Liefert PV-Leistungsprognosen (kW) für 0–48 Stunden für eine einzelne PV-Anlage.

**Modelltyp:**
- **Gradient Boosting Model** (Standard): Nutzt GFS/ICON/ECMWF NWP-Daten (9 Variablen: Visibility, Wind, Temperatur, Niederschlag, Strahlung, Bewölkung etc.)
- **XGBoost Model**: Nutzt Open-Meteo-Variablen (Temperatur, Feuchtigkeit, Taupunkt, Niederschlag, Luftdruck, Bewölkung, Wind, Strahlung etc.)
- Trainiert auf 25.000 PV-Anlagen mit über 5 Jahren PV-Historie (UK-Daten)

**Genauigkeit:**
- Gradient Boosting: MAE 0,19 kW über alle Horizonte (0–48h), MAE 13,0% der Nennleistung (ohne Nachtstunden)
- XGBoost: MAE 0,12 kW (gesamt), MAE 0,21 kW (ohne Nachtstunden)
- Einschränkung: Nur auf UK-Daten trainiert, Anwendung auf andere Regionen mit Vorsicht

**Kosten/Lizenz:** MIT-Lizenz, kostenlos, `pip install quartz-solar-forecast`

**Links:**
- GitHub: https://github.com/openclimatefix/open-source-quartz-solar-forecast
- PyPI: https://pypi.org/project/quartz-solar-forecast/
- API: https://open.quartz.solar
- Colab-Notebook: https://colab.research.google.com/drive/1qKDFRpq4Hk-LHgWuDsz_Najc3Zq-GVNY

### 6.2 rany2/open-meteo-solar-forecast

**Beschreibung:** Python-Modul, das Open-Meteo-Daten nutzt, um Solarproduktionsprognosen zu berechnen. Basiert auf der pvlib-Methodik (Strahlung → PV-Leistung).

**Features:**
- Unterstützt mehrere PV-Arrays (verschiedene Neigungen/Azimute)
- Multi-Inverter-Unterstützung
- Horizont-Shading (Horizon Map)
- Partial Shading (experimentell)
- Snow-Coverage-Modell
- Tracking (Azimut/Tilt/Dual)
- 15-minütige Auflösung

**Genauigkeit:** Abhängig von Open-Meteo-Datenqualität und Parametrisierung (keine publizierten Benchmarks)

**Kosten/Lizenz:** MIT-Lizenz, kostenlos, `pip install open-meteo-solar-forecast`

**Links:**
- GitHub: https://github.com/rany2/open-meteo-solar-forecast
- HA-Integration: https://github.com/rany2/ha-open-meteo-solar-forecast

### 6.3 Weitere GitHub-Projekte

| Projekt | Beschreibung | Link |
|---------|-------------|------|
| **Solar-Forecast-ML** (Zara-Toorox) | Lokales AI-Solar-Forecast für Home Assistant (Attention Transformer), vollständig lokal | https://github.com/Zara-Toorox/Solar-Forecast-ML |
| **smart-persistence-model** (Felix561) | Python-Implementierung des Smart Persistence Model für Kurzzeit-PV-Prognose | https://github.com/Felix561/smart-persistence-model |
| **ha-pvnode** (darwindaume) | Home Assistant PV-Node-Integration | https://github.com/darwindaume/ha-pvnode |
| **PVForecast** (StefaE) | PV-Prognose zur Optimierung des Stromverbrauchs, Integration mit solaranzeige | https://github.com/StefaE/PVForecast |
| **fmi-open-pv-forecast** (fmidev) | Wettervorhersage-bewusste PV-Prognose (nicht mehr gepflegt) | https://github.com/fmidev/fmi-open-pv-forecast |
| **climate-aware-pv-forecasting** (Jouqio) | Klimabewusste PV-Prognose | https://github.com/Jouqio/climate-aware-pv-forecasting |

### 6.4 Solar Forecast Arbiter (EPRI)

**Beschreibung:** Open-Source-Plattform für den Austausch und die Bewertung von Solarprognosen. Bietet REST-API für Daten-Upload und -Vergleich. Wird hauptsächlich für Forschung und Benchmarking genutzt.

**Links:**
- Website: https://forecastarbiter.epri.com
- Dokumentation: https://forecastarbiter.epri.com/documentation/

---

## 7. Home Assistant Integrationen für Solar-Prognose

### 7.1 Solcast (Custom Component / HACS)

- **Beschreibung:** Nutzt die Solcast-API für PV-Leistungsprognosen
- **Features:** Automatische PV-Tuning, History, adaptive Shading-Dämpfung
- **Kosten:** Free Tier (10 Calls/Tag) oder kostenpflichtig
- **GitHub:** https://github.com/BJReplay/ha-solcast-solar (Custom Component)
- **HA-Community:** https://community.home-assistant.io/t/solcast-global-solar-power-forecast-integration/

### 7.2 Forecast.Solar (Eingebaut)

- **Beschreibung:** Offizielle HA-Integration für Forecast.Solar
- **Features:** Einfache Konfiguration, keine API-Key für Public-Tier
- **Kosten:** Free (Public-Tier, rate-limited) oder kostenpflichtig
- **Dokumentation:** https://www.home-assistant.io/integrations/forecast_solar/

### 7.3 Open-Meteo Solar Forecast (Custom Component / HACS)

- **Beschreibung:** Basiert auf Forecast.Solar-Integration, nutzt aber Open-Meteo-API
- **Features:** Kostenloser, oft als genauer wahrgenommen als Forecast.Solar
- **Kosten:** Kostenlos (Open-Meteo Free Tier)
- **GitHub:** https://github.com/rany2/ha-open-meteo-solar-forecast
- **HA-Community:** https://community.home-assistant.io/t/open-meteo-solar-forecast/

### 7.4 Solcast Solar Enhanced (Add-on)

- **Beschreibung:** Companion-Add-on für die Solcast-Integration mit erweiterten Features (History, PV-Tuning, adaptive Dämpfung)
- **GitHub:** https://community.home-assistant.io/t/solcast-solar-enhanced-built-in-history-automatic-pv-tuning-adaptive-shading-dampening-companion-to-ha-solcast-solar/

### 7.5 Solar-Forecast-ML (Custom Integration)

- **Beschreibung:** Lokales AI-Solar-Forecast (Attention Transformer) für Home Assistant
- **Features:** Vollständig lokal, keine Cloud-Abhängigkeit, Datenschutz
- **Kosten:** Kostenlos (Open Source)
- **GitHub:** https://github.com/Zara-Toorox/Solar-Forecast-ML

---

## 8. Vergleichstabelle

| Kriterium | Open-Meteo | Forecast.Solar | pvlib-python | Solcast (Free) | Quartz Solar | Open-Meteo Solar Forecast |
|-----------|-----------|----------------|--------------|----------------|-------------|--------------------------|
| **Typ** | NWP-Datenprovider | Empirisches Modell | Framework | Satellit+NWP | ML-Modell | Strahlung→PV |
| **Kosten** | Kostenlos (10k/Tag) | Free (rate-limited) | Open Source | 10 Calls/Tag | Open Source | Open Source |
| **Lizenz** | AGPLv3/CC BY 4.0 | Proprietär | BSD-3 | Proprietär | MIT | MIT |
| **PV-Leistung** | Nein (nur Strahlung) | Ja | Ja (mit Parametrisierung) | Ja | Ja | Ja |
| **Horizont** | Bis 16 Tage | Bis 7 Tage | Abhängig von Eingabe | Bis 14 Tage | 0–48 Stunden | Bis 16 Tage |
| **Auflösung** | Stündlich/15-min | Stündlich | Abhängig | 30-min/Stündlich | Stündlich | Stündlich/15-min |
| **Genauigkeit** | Modellabhängig | Community: moderat | 10–20% nRMSE | Sehr gut (Referenz) | MAE 0,19 kW | Modellabhängig |
| **Self-Hosting** | Ja (AGPLv3) | Nein | Ja | Nein | Ja | Ja |
| **HA-Integration** | Custom (HACS) | Eingebaut | Nein (manuell) | Custom (HACS) | Nein | Custom (HACS) |
| **Datenquellen** | 15+ Wetterdienste | PVGIS+Wetter | Konfigurierbar | Satellit+NWP | GFS/ICON/ECMWF | Open-Meteo |

---

## 9. Empfehlungen

### Für private Anwendungen (kostenlos)

1. **Beste Gesamtlösung (HA):** **Open-Meteo Solar Forecast** (HACS)
   - Kostenlos, oft als genauer wahrgenommen als Forecast.Solar
   - Nutzt Open-Meteo (10.000 Calls/Tag kostenlos)
   - Einfache Konfiguration, basiert auf Forecast.Solar-Integration

2. **Höchste Genauigkeit (Free Tier):** **Solcast** (10 Calls/Tag)
   - Beste Genauigkeit unter den kostenlosen Optionen
   - Erfordert Verifizierung der Wohnadresse
   - Limit: 10 Calls/Tag (ausreichend für tägliche Updates)

3. **Für Entwickler/Bastler:** **pvlib-python + Open-Meteo**
   - Maximale Flexibilität, eigene Modelle möglich
   - Open-Meteo liefert Strahlungsdaten (GHI, DNI, GTI etc.)
   - pvlib berechnet PV-Leistung aus Strahlung + Systemparametern
   - Kombinierbar mit ML-Modellen (Quartz Solar als Referenz)

4. **Lokal/Privacy-first:** **Solar-Forecast-ML** (Zara-Toorox)
   - Vollständig lokal, keine Cloud-Abhängigkeit
   - Attention Transformer, trainiert für HA
   - Noch in Entwicklung, aber vielversprechend

5. **Für Experimente/Research:** **Open-Source Quartz Solar Forecast**
   - ML-Modell (Gradient Boosting / XGBoost)
   - MAE 0,19 kW (UK-Daten)
   - Einschränkung: Nur UK-Training, Anwendung auf andere Regionen mit Vorsicht

### Nicht empfohlen für private kostenlose Nutzung

- **OpenWeatherMap Solar Irradiance API:** Kostenpflichtig, keine kostenlose Solar-Strahlung
- **Forecast.Solar (kostenpflichtige Tiers):** Nur Public-Tier kostenlos, rate-limited
- **Solcast (kostenpflichtige Tiers):** Enterprise-Pläne für höhere Volumina

---

## Quellen

1. Open-Meteo: https://open-meteo.com
2. Forecast.Solar: https://forecast.solar / https://doc.forecast.solar
3. pvlib-python: https://pvlib-python.readthedocs.io
4. Solcast: https://solcast.com/free-rooftop-solar-forecasting
5. OpenWeatherMap: https://openweathermap.org
6. Open-Source Quartz Solar Forecast: https://github.com/openclimatefix/open-source-quartz-solar-forecast
7. rany2/open-meteo-solar-forecast: https://github.com/rany2/open-meteo-solar-forecast
8. Home Assistant Forecast.Solar: https://www.home-assistant.io/integrations/forecast_solar/
9. HA Open-Meteo Solar Forecast: https://github.com/rany2/ha-open-meteo-solar-forecast
10. HA Community (Solar Forecast Vergleich): https://community.home-assistant.io/t/open-meteo-solar-forecast/733073
11. Solar Forecast Arbiter: https://forecastarbiter.epri.com
12. Solar-Forecast-ML: https://github.com/Zara-Toorox/Solar-Forecast-ML