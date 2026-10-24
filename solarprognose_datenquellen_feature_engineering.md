# Solarprognosen: Kostenlose Datenquellen und Feature-Engineering

> Privat nutzbar · Stand: 2026 · Erstellt für das Projekt `prognosemodelle`

---

## 1. Kostenlose Wetter-APIs

### 1.1 Open-Meteo (Empfehlung #1 für Privatnutzer)

| Eigenschaft | Details |
|---|---|
| **Kosten** | Kostenlos (non-commercial), CC BY 4.0 Lizenz |
| **API-Key** | Nicht erforderlich |
| **Limits** | ~10.000 Calls/Tag (non-commercial) |
| **Modelle** | 30+ (ECMWF, DWD ICON, NOAA, Météo-France, JMA, etc.) |
| **Auflösung** | 1–2 km (regional) bis 9–11 km (global), normalisiert auf stündlich |
| **Historie** | ERA5 Reanalysis ab 1940, Historical Forecast ab 2021 |
| **Solarvariablen** | GHI, DHI, DNI, GTI, instantane Werte |
| **Updates** | Globale Modelle alle 6 h, regionale (ICON-D2, HRRR, AROME) alle 1–3 h |
| **Self-Hosting** | Ja (AGPLv3, unbegrenzte Calls) |

**Vorteile:** Kein API-Key, extrem einfach (HTTP GET → JSON), model-divers, historische Daten für ML-Training, PVOutput-ähnliche Community (solXpect Solar-App nutzt Open-Meteo).

**Nachteile:** Non-commercial-Lizenz (kommerzielle Nutzung → Bezahlplan), keine offiziellen Accuracy-Benchmarks auf Stationsbasis, kein Ensemble-Output im Free-Tier.

**Integration:**
```python
import openmeteo_requests
om = openmeteo_requests.Client()
params = {
    "latitude": 52.52, "longitude": 13.41,
    "hourly": ["temperature_2m", "shortwave_radiation", "direct_normal_irradiance",
               "diffuse_radiation", "cloud_cover", "wind_speed_10m"],
    "forecast_days": 7
}
responses = om.weather_api("https://api.open-meteo.com/v1/forecast", params=params)
```

### 1.2 OpenWeatherMap (Free Tier)

| Eigenschaft | Details |
|---|---|
| **Kosten** | Free Tier: 1.000 Calls/Tag (One Call API) |
| **API-Key** | Erforderlich (kostenlose Registrierung) |
| **Limits** | 60 Calls/Min, 1.000/Tag (Free) |
| **Auflösung** | 2 h Update-Frequenz (Free) |
| **Forecast** | 5 Tage (Free) |
| **Solar** | Separates Solar Irradiance API (GHI, DNI, DHI, Clear-Sky/Cloudy-Sky Modelle) |
| **Historie** | 40 Jahre (kostenpflichtig) |

**Vorteile:** Kommerzielle Nutzung im Free-Tier erlaubt, Solar-Irradiance-API mit Clear-Sky/Cloudy-Sky-Modellen.

**Nachteile:** Tighte Limits (1.000/Tag), Solar-API separate Endpunkte, historische Daten nur kostenpflichtig.

### 1.3 WeatherAPI (Free Tier)

| Eigenschaft | Details |
|---|---|
| **Kosten** | Free Tier: 100.000 Calls/Monat |
| **API-Key** | Erforderlich |
| **Limits** | 100k/Monat (Free) |
| **Forecast** | 3 Tage (Free) |
| **Solar** | Solar-Daten in Forecast enthalten (UV-Index, Strahlung) |
| **Historie** | 7 Tage (Free), mehr kostenpflichtig |

**Vorteile:** Generöseste Call-Limits im Free-Tier (100k/Monat), Python SDK verfügbar.

**Nachteile:** Nur 3 Tage Forecast, historische Daten stark limitiert (7 Tage Free).

### 1.4 DWD (Deutscher Wetterdienst) — MOSMIX

| Eigenschaft | Details |
|---|---|
| **Kosten** | Vollständig kostenlos, Open Data |
| **API-Key** | Nicht erforderlich |
| **Daten** | MOSMIX L/S (Modelloutput, stationsbasiert) |
| **Auflösung** | ~7 km, stündlich, 10-Tage-Forecast |
| **Strahlung** | Strahlungsdaten (rad1h, rad24h) in MOSMIX |
| **Zugang** | FTP/Open Data Server (dwd.de/opendata) |

**Vorteile:** Offizielle deutsche Wetterdaten, hohe Qualität für Deutschland, keine Limits.

**Nachteile:** Kein REST-API (FTP/KML/GRIB), Parsing aufwändig, nur Deutschland.

### 1.5 NOAA/NWS (US-only)

- **Kosten:** Kostenlos, keine Registrierung
- **Abdeckung:** Nur USA
- **Auflösung:** ~2.5 km (HRRR), stündlich
- **Solar:** GHI über NWP-Modelle

---

## 2. Strahlungsdaten (DWD, Copernicus, ERA5, CAMS)

### 2.1 ERA5 (ECMWF Reanalysis)

| Eigenschaft | Details |
|---|---|
| **Zeitraum** | 1940 – heute |
| **Auflösung** | 0.1°–0.25° (~11–28 km), stündlich |
| **Variablen** | SSRD (Surface Solar Radiation Downwards), Strahlungskomponenten |
| **Zugang** | Copernicus Climate Data Store (CDS), cdsapi Python |
| **Kosten** | Kostenlos (Registrierung erforderlich) |
| **Qualität** | Hoch (Reanalysis, assimiliert Beobachtungen) |

**Integration:**
```python
import cdsapi
c = cdsapi.Client()
c.retrieve('reanalysis-era5-single-levels', {
    'product_type': 'reanalysis',
    'variable': 'surface_solar_radiation_downwards',
    'year': '2023', 'month': '06', 'day': '15',
    'time': '12:00',
    'area': [53, 12, 50, 15],  # N, W, S, E
    'format': 'netcdf'
}, 'era5_ssr.nc')
```

**Einsatz:** ML-Training (lange Historie), Bias-Korrektur, Klimabaselines.

### 2.2 CAMS (Copernicus Atmosphere Monitoring Service)

| Eigenschaft | Details |
|---|---|
| **Zeitraum** | 2004 – heute |
| **Auflösung** | ~3–5 km (regional, MSG-basiert), 15-minütlich |
| **Variablen** | GHI, BHI (Beam Horizontal), DHI, BNI (Beam Normal), Clear-Sky Index |
| **Zugang** | CAMS Solar Radiation Service, pvlib iotools, ADS (Atmosphere Data Store) |
| **Kosten** | Kostenlos (Registrierung) |
| **Qualität** | Sehr hoch (Satellitenbasiert, validiert gegen Bodenstationen) |

**Vorteile:** Spezialisiert auf Solarstrahlung, hohe räumliche/temporale Auflösung, Aerosol- und Wolkeninformationen.

**Integration (pvlib):**
```python
import pvlib
data, metadata = pvlib.iotools.get_cams(
    latitude=52.52, longitude=13.41,
    start='2023-06-01', end='2023-06-30',
    email='user@example.com'
)
# Gibt GHI, BHI, DHI, BNI, Clear-Sky Index zurück
```

### 2.3 DWD Strahlungsdaten

| Eigenschaft | Details |
|---|---|
| **Zeitraum** | Ab 2000 (je nach Station) |
| **Auflösung** | Stationsbasiert (Punkt), 10-minütlich/stündlich |
| **Variablen** | Globalstrahlung, Diffusstrahlung, Sonnenscheindauer |
| **Zugang** | DWD Open Data (FTP), Climate Data Center |
| **Qualität** | Sehr hoch (Bodenmessungen, pyranometer) |
| **Abdeckung** | Deutschland (~50+ Strahlungsstationen) |

**Einsatz:** Ground-Truth für Validierung, Bias-Korrektur von Satellitendaten.

### 2.4 Open-Meteo Solar Radiation (historisch)

- **Zeitraum:** Ab 1940 (ERA5-basiert) bzw. 2021 (Historical Forecast)
- **Auflösung:** 1–11 km, stündlich
- **Variablen:** GHI, DHI, DNI, GTI, Instant-Werte
- **Vorteil:** Einfachster Zugang (REST API, kein Key), direkt für ML-Pipelines

---

## 3. Satellitenbasierte Strahlung

### 3.1 MSG/SEVIRI (Meteosat Second Generation)

| Eigenschaft | Details |
|---|---|
| **Satellit** | Meteosat-11 (0°), Meteosat-9 (IODC) |
| **Abdeckung** | Europa, Afrika, Teile Südamerika, Indischer Ozean |
| **Auflösung** | ~3 km (Nadir), 15-minütlich |
| **Kanäle** | 12 (inkl. VIS 0.6 µm für Wolken) |
| **Zugang** | EUMETSAT, CAMS, Open-Meteo Satellite Radiation API |
| **Daten** | GHI, DNI, DHI (abgeleitet) |

**Open-Meteo Satellite Radiation API:**
- Nutzt Himawari-9 (JMA/JAXA) für Asien/Australien
- MSG für Europa/Afrika
- 10-minütliche Daten, 30 Min. Verzögerung
- Archiv ab 2015

**Integration:**
```python
import openmeteo_requests
params = {
    "latitude": 52.52, "longitude": 13.41,
    "minutely_15": ["shortwave_radiation", "direct_normal_irradiance",
                    "diffuse_radiation"],
    "past_days": 30
}
responses = om.weather_api("https://satellite-api.open-meteo.com/v1/satellite-radiation", params=params)
```

### 3.2 Himawari-8/9

| Eigenschaft | Details |
|---|---|
| **Satellit** | Himawari-9 (JMA) |
| **Abdeckung** | Asien, Australien, Indischer Ozean, Pazifik |
| **Auflösung** | ~5 km (0.05°), 10-minütlich |
| **Zugang** | JAXA P-Tree, Open-Meteo Satellite API |
| **Archiv** | Ab 2015 |

### 3.3 GOES (Amerika)

- **Satellit:** GOES-16/17/18
- **Abdeckung:** Nord-/Südamerika
- **Auflösung:** ~2 km, 5–15 min
- **Zugang:** NOAA, AWS Open Data

### 3.4 Satellitenbasierte Strahlung aus der Literatur

- **AMATERASS** (Himawari-basiert): Validiert gegen SKYNET-Stationen in Japan
- **CAMS Radiation Service:** MSG + Himawari fusioniert, 15-min, 3–5 km
- **Fehler:** Typischerweise 5–15% RMSE für GHI (abhängig von Region/Wolken)

---

## 4. Historische PV-Daten

### 4.1 PVOutput.org

| Eigenschaft | Details |
|---|---|
| **Typ** | Community-Plattform (kostenlos) |
| **API-Limits** | 60 Requests/Stunde, 900 PV-System-Jahre/Stunde |
| **Auflösung** | 5-minütlich (Live), 15-min aggregiert |
| **Daten** | PV-Erzeugung (kWh/kW), Verbrauch, Wetter (optional) |
| **Metadaten** | Systemgröße, Orientierung, Neigung, Standort (anonymisiert) |
| **Zugang** | REST API (API-Key erforderlich, kostenlos) |

**Python-Integration:**
```python
# pvoutput Python-Paket
import pvoutput
api = pvoutput.PVOutput(apikey='YOUR_KEY', systemid='YOUR_ID')
data = api.get_output(date='20230615')
```

**Einsatz:** ML-Training (PV-Erzeugung als Target), Benchmarking, Validierung.

**Einschränkungen:** Datenqualität variiert (Community-Upload), Standortinformationen oft grob (PLZ), Systemkonfiguration nicht immer vollständig.

### 4.2 Open-PV (NREL)

- **Typ:** US-amerikanische PV-Installationsdatenbank
- **Daten:** Systemgröße, Kosten, Installationsdatum, Standort (ZIP)
- **Auflösung:** Keine Zeitreihen (nur Metadaten)
- **Zugang:** API (kostenlos, NREL)
- **Einsatz:** Systemmetadaten, Kostenanalysen, nicht für Prognosen geeignet

### 4.3 Weitere Quellen

| Quelle | Beschreibung | Geeignet für |
|---|---|---|
| **Home Assistant Energy Dashboard** | Eigene PV-Daten (falls vorhanden) | Ground-Truth, Training |
| **Enphase/SMA API** | Hersteller-APIs (Free Tier) | Eigene Anlage |
| **Solcast** | Solar Forecasting API (Free Tier: 10 Calls/Tag) | Benchmarking |
| **Forecast.Solar** | Solar Prognose API (Free Tier) | Benchmarking/Validierung |
| **Kaggle Solar Datasets** | Verschiedene PV-Datensätze | ML-Training, Experimente |

### 4.4 Datenqualität PVOutput

- **Lücken:** Fehlende Tage, Sensorausfälle
- **Rauschen:** Schatten, Verschmutzung, Verschattung durch Gebäude
- **Inkonsistenz:** Unterschiedliche Zeitzonen, Auflösungen
- **Metadaten:** Nicht immer vollständig (Orientierung, Neigung)

---

## 5. Feature Engineering

### 5.1 Clear-Sky Index (Kt / CSI)

Der Clear-Sky Index ist das Verhältnis der gemessenen Strahlung zur theoretischen Clear-Sky-Strahlung:

```
Kt = GHI_gemessen / GHI_clear_sky
```

**Berechnung (pvlib):**
```python
import pvlib
from pvlib import clearsky

# Standort
location = pvlib.location.Location(lat, lon, tz='Europe/Berlin')

# Clear-Sky-Modell (Ineichen oder Simplified Solis)
cs = location.get_clearsky(times, model='ineichen')

# Clear-Sky Index
kt = ghi_measured / cs['ghi']
kt = kt.clip(0, 1.2)  # Physikalische Grenzen
```

**Features:**
- `clear_sky_index` (stündlich, 0–1.2)
- `clear_sky_ghi` (theoretische Strahlung)
- `clear_sky_dni`, `clear_sky_dhi`

### 5.2 Solar Position

```python
solpos = location.get_solarposition(times)
# Features:
# - zenith (Zenithwinkel, 0° = Sonne im Zenit)
# - azimuth (Azimut, 0° = Nord, 180° = Süd)
# - elevation (Höhenwinkel)
# - equation_of_time
```

**Abgeleitete Features:**
- `sin(azimuth)`, `cos(azimuth)` (zyklische Kodierung)
- `cos(zenith)` (proportional zu Strahlung)
- `air_mass` (Luftmasse)
- `sunrise`, `sunset` (binär oder Zeitdifferenz)
- `hour_of_day`, `day_of_year` (zyklisch kodiert)

### 5.3 Temperatur-Features

| Feature | Beschreibung | Quelle |
|---|---|---|
| `temp_air` | Lufttemperatur 2m | Wetter-API |
| `temp_module` | Modultemperatur (geschätzt) | Berechnet |
| `temp_delta` | Differenz Luft/Modul | Berechnet |

**Modultemperatur (NOCT-Modell):**
```python
# Vereinfachte Schätzung
temp_module = temp_air + (noct - 20) / 800 * ghi
# NOCT ≈ 45°C (typisch für kristalline Module)
```

**Effekt auf PV-Erzeugung:** Ca. -0.4%/°C über 25°C (Temperaturkoeffizient).

### 5.4 Bewölkungs-Features

| Feature | Beschreibung | Quelle |
|---|---|---|
| `cloud_cover` | Gesamtbewölkung (%) | Wetter-API |
| `cloud_cover_low/mid/high` | Bewölkung nach Schicht | Wetter-API (manche) |
| `cloud_type` | Wolkenart | Satellit |
| `clear_sky_index` | Kt (siehe 5.1) | Berechnet |

**Wolken-Transit-Features:**
- `cloud_cover_change` (Differenz t-1 → t)
- `cloud_cover_rolling_mean` (3h, 6h)
- `cloud_cover_rolling_std` (Variabilität)

### 5.5 Weitere Features

| Feature | Beschreibung | Quelle |
|---|---|---|
| `wind_speed` | Windgeschwindigkeit 10m | Wetter-API |
| `wind_direction` | Windrichtung (zyklisch) | Wetter-API |
| `humidity` | Relative Feuchte | Wetter-API |
| `pressure` | Luftdruck | Wetter-API |
| `aerosol_optical_depth` | Aerosol-Gehalt | CAMS |
| `precipitation` | Niederschlag | Wetter-API |
| `snow_depth` | Schneehöhe | Wetter-API |
| `soiling` | Verschmutzung (geschätzt) | Berechnet (Tage seit Regen) |

### 5.6 Lag-Features und Rolling Statistics

```python
# Historische Werte
df['ghi_lag_1h'] = df['ghi'].shift(1)
df['ghi_lag_24h'] = df['ghi'].shift(24)

# Rolling Statistics
df['ghi_rolling_mean_3h'] = df['ghi'].rolling(3).mean()
df['ghi_rolling_std_6h'] = df['ghi'].rolling(6).std()
df['ghi_rolling_max_24h'] = df['ghi'].rolling(24).max()
```

### 5.7 pvlib Python — Zentrale Bibliothek

**pvlib** ist die zentrale Python-Bibliothek für Solar-Energie-Berechnungen:

```python
import pvlib

# Standort
location = pvlib.location.Location(lat, lon, tz='Europe/Berlin', altitude=34)

# Solarposition
solpos = location.get_solarposition(times)

# Clear-Sky-Modell
cs = location.get_clearsky(times, model='ineichen')

# PV-Leistung (vereinfacht)
pv_power = pvlib.pvsystem.pvwatts_dc(
    ghi=ghi, dni=dni, dhi=dhi,
    poa_global=poa,  # Plane of Array
    temp_cell=temp_module,
    pdc0=5000,  # Nennleistung in W
    gamma_pdc=-0.004  # Temperaturkoeffizient
)
```

**pvlib iotools** bietet Zugang zu:
- PVGIS (EU Strahlungsdaten)
- CAMS (Copernicus)
- NOAA SURFRAD
- NREL (US)
- Solcast (API)

---

## 6. Datenqualität und Missing Data Handling

### 6.1 Typische Datenprobleme

| Problem | Ursache | Häufigkeit |
|---|---|---|
| **Fehlende Werte (NaN)** | Sensorausfall, API-Downtime | 1–5% |
| **Ausreißer** | Sensorfehler, Verschattung | 0.1–1% |
| **Zeitstempel-Lücken** | Netzwerkprobleme, API-Limits | Variabel |
| **Zeitzonen-Fehler** | Sommerzeit, UTC vs. lokal | Häufig bei Community-Daten |
| **Negative Strahlung** | Sensorrauschen bei Nacht | Selten |
| **Überstrahlung** | Reflexionen, Sensorfehler | Selten |

### 6.2 Imputation-Strategien

| Methode | Beschreibung | Einsatz |
|---|---|---|
| **Lineare Interpolation** | Zwischen bekannten Werten | Kurze Lücken (<3h) |
| **Zeitbasierte Interpolation** | Berücksichtigt Tageszeit | Mittlere Lücken (3–6h) |
| **Clear-Sky-Fallback** | Clear-Sky-Modell als Ersatz | Strahlungslücken |
| **KNN-Imputation** | Ähnliche Zeitpunkte | Multivariate Daten |
| **Forward/Backward Fill** | Letzter bekannter Wert | Sehr kurze Lücken |
| **Modellbasierte Imputation** | ML-Modell (Autoencoder, BiLSTM) | Komplexe Muster |

**Best Practice für Solar:**
```python
# 1. Physikalische Grenzen prüfen
df['ghi'] = df['ghi'].clip(0, 1400)  # Max ~1400 W/m²

# 2. Nacht-Werte auf 0 setzen
night_mask = (df['solar_elevation'] <= 0)
df.loc[night_mask, 'ghi'] = 0

# 3. Kurze Lücken interpolieren
df['ghi'] = df['ghi'].interpolate(method='time', limit=3)

# 4. Längere Lücken mit Clear-Sky füllen
mask = df['ghi'].isna() & (df['solar_elevation'] > 0)
df.loc[mask, 'ghi'] = df.loc[mask, 'clear_sky_ghi'] * 0.5  # Konservativ

# 5. Verbleibende NaN entfernen oder als Missing markieren
```

### 6.3 Ausreißer-Erkennung

```python
# Z-Score basiert
from scipy import stats
z_scores = stats.zscore(df['ghi'].dropna())
outliers = abs(z_scores) > 3

# Physikalisch basiert
max_ghi = 1400  # W/m²
min_ghi = 0
outliers = (df['ghi'] > max_ghi) | (df['ghi'] < min_ghi)

# Clear-Sky-Index basiert
df['kt'] = df['ghi'] / df['clear_sky_ghi']
outliers = (df['kt'] > 1.3) | (df['kt'] < 0)
```

### 6.4 Datenvalidierung (Quality Checks)

- **Vollständigkeit:** Anteil fehlender Werte < 5%
- **Konsistenz:** GHI = DNI·cos(θz) + DHI
- **Plausibilität:** 0 ≤ GHI ≤ 1400 W/m², 0 ≤ Kt ≤ 1.3
- **Zeitliche Kontinuität:** Keine Sprünge > 500 W/m² in 15 min (ohne Wolkenbruch)
- **Nacht-Check:** GHI ≈ 0 bei Sonnenhöhe < 0°

### 6.5 Datenqualität nach Quelle

| Quelle | Qualität | Auflösung | Lücken | Empfehlung |
|---|---|---|---|---|
| DWD Bodenstation | ★★★★★ | 10 min | Selten | Ground-Truth |
| CAMS Satellit | ★★★★☆ | 15 min, 3–5 km | Selten | Sehr gut |
| ERA5 Reanalysis | ★★★☆☆ | 1 h, 11–28 km | Keine | Training/Baseline |
| Open-Meteo Forecast | ★★★☆☆ | 1 h, 1–11 km | Selten | Operational |
| PVOutput | ★★★☆☆ | 5–15 min | Häufig | Target-Variable |
| WeatherAPI | ★★★☆☆ | 1 h, 1 km | Selten | Operational |

---

## 7. Datenpipelines und Automatisierung

### 7.1 Empfehlung für Privatnutzer: Einfacher Cron + Python

Für private Solarprognosen ist ein vollwertiger Orchestrator (Airflow/Prefect) meist überdimensioniert. Empfohlen:

```
┌─────────────┐     ┌──────────────┐     ┌─────────────┐
│  Cron Job   │ ──► │  Python      │ ──► │  SQLite/    │
│  (stündlich)│     │  Pipeline    │     │  PostgreSQL │
└─────────────┘     └──────────────┘     └─────────────┘
                           │
                    ┌──────┴──────┐
                    │  Open-Meteo │
                    │  CAMS API   │
                    │  PVOutput   │
                    └─────────────┘
```

**Cron-Beispiel:**
```bash
# Stündliche Datenabfrage
0 * * * * /usr/bin/python3 /home/user/solar_pipeline/fetch_data.py >> /var/log/solar.log 2>&1

# Tägliche Modell-Neutrainierung
0 2 * * * /usr/bin/python3 /home/user/solar_pipeline/retrain.py >> /var/log/solar.log 2>&1
```

### 7.2 Prefect (für komplexere Pipelines)

- **Vorteile:** Python-native, einfach zu starten, Retries, Caching, Dashboard
- **Nachteile:** Infrastruktur (Server oder Cloud), Overhead für einfache Tasks
- **Einsatz:** Wenn mehrere Datenquellen, komplexe Transformationen, ML-Training

```python
from prefect import flow, task

@task(retries=3)
def fetch_weather(lat, lon):
    # Open-Meteo API Call
    ...

@task
def transform_data(raw_data):
    # Feature Engineering
    ...

@flow
def solar_data_pipeline():
    raw = fetch_weather(52.52, 13.41)
    features = transform_data(raw)
    store(features)
```

### 7.3 Apache Airflow

- **Vorteile:** Industry Standard, riesiges Ökosystem, Skalierbar
- **Nachteile:** Komplexe Infrastruktur (Scheduler, Worker, DB, Webserver), Overhead
- **Einsatz:** Enterprise/Produktion, nicht für private Projekte empfohlen

### 7.4 Weitere Optionen

| Tool | Komplexität | Vorteile | Nachteile |
|---|---|---|---|
| **Cron + Python** | ★☆☆☆☆ | Einfach, keine Infrastruktur | Kein Monitoring, keine Retries |
| **Prefect** | ★★☆☆☆ | Python-native, Retries, Dashboard | Server/Cloud nötig |
| **Airflow** | ★★★★☆ | Skalierbar, Ökosystem | Hoher Overhead |
| **Dagster** | ★★★☆☆ | Datenorientiert, Testing | Lernkurve |
| **Kestra** | ★★☆☆☆ | YAML-basiert, leichtgewichtig | Weniger Python-native |
| **GitHub Actions** | ★★☆☆☆ | Kostenlos, CI/CD | Nicht für kontinuierliche Pipelines |

### 7.5 Empfohlene Pipeline-Architektur (Privat)

```
solar_pipeline/
├── config/
│   ├── locations.yaml        # Standorte
│   └── features.yaml         # Feature-Definitionen
├── src/
│   ├── fetchers/
│   │   ├── openmeteo.py      # Wetter + Strahlung
│   │   ├── cams.py           # CAMS Solar (pvlib)
│   │   └── pvoutput.py       # PV-Daten
│   ├── features/
│   │   ├── solar_position.py # pvlib
│   │   ├── clear_sky.py      # Clear-Sky Index
│   │   └── temperature.py    # Modultemperatur
│   ├── storage/
│   │   └── database.py       # SQLite/PostgreSQL
│   └── models/
│       └── train.py          # ML-Training
├── data/
│   └── solar.db              # SQLite
├── logs/
└── cron.sh
```

---

## 8. Speicherung

### 8.1 SQLite (Empfehlung für Privatnutzer)

| Eigenschaft | Details |
|---|---|
| **Kosten** | Kostenlos, Open Source |
| **Setup** | Kein Server, Datei-basiert |
| **Performance** | Gut bis ~1M Zeilen, dann langsam |
| **Zeitreihen** | Manuelle Partitionierung nötig |
| **Gleichzeitigkeit** | Single-Writer, Multi-Reader |
| **Backup** | Datei kopieren |

**Schema-Beispiel:**
```sql
CREATE TABLE weather_data (
    timestamp DATETIME NOT NULL,
    location_id TEXT NOT NULL,
    temp_air REAL,
    ghi REAL,
    dni REAL,
    dhi REAL,
    cloud_cover REAL,
    wind_speed REAL,
    humidity REAL,
    PRIMARY KEY (timestamp, location_id)
);

CREATE TABLE pv_output (
    timestamp DATETIME NOT NULL,
    system_id TEXT NOT NULL,
    power_kw REAL,
    energy_kwh REAL,
    PRIMARY KEY (timestamp, system_id)
);

CREATE TABLE features (
    timestamp DATETIME NOT NULL,
    location_id TEXT NOT NULL,
    solar_zenith REAL,
    solar_azimuth REAL,
    clear_sky_ghi REAL,
    clear_sky_index REAL,
    temp_module REAL,
    PRIMARY KEY (timestamp, location_id)
);

-- Index für schnelle Abfragen
CREATE INDEX idx_weather_time ON weather_data(timestamp);
CREATE INDEX idx_pv_time ON pv_output(timestamp);
```

**Vorteile:** Kein Setup, portabel, ausreichend für private Projekte.

**Nachteile:** Keine nativen Zeitreihen-Funktionen, keine Kompression, Skalierung begrenzt.

### 8.2 PostgreSQL

| Eigenschaft | Details |
|---|---|
| **Kosten** | Kostenlos, Open Source |
| **Setup** | Server erforderlich (Docker empfohlen) |
| **Performance** | Exzellent, skalierbar |
| **Zeitreihen** | Mit TimescaleDB-Erweiterung |
| **Gleichzeitigkeit** | Multi-Writer, MVCC |
| **Backup** | pg_dump, WAL-Archivierung |

**Docker-Setup:**
```yaml
# docker-compose.yml
services:
  postgres:
    image: timescale/timescaledb:latest-pg16
    environment:
      POSTGRES_DB: solar
      POSTGRES_USER: solar
      POSTGRES_PASSWORD: solar123
    volumes:
      - pgdata:/var/lib/postgresql/data
    ports:
      - "5432:5432"
volumes:
  pgdata:
```

### 8.3 TimescaleDB (PostgreSQL-Erweiterung)

| Eigenschaft | Details |
|---|---|
| **Kosten** | Kostenlos (Open Source), Tiger Cloud (managed) |
| **Setup** | PostgreSQL + Extension |
| **Performance** | 10–100x schneller für Zeitreihen-Queries |
| **Features** | Hypertables, Continuous Aggregates, Kompression, Retention Policies |
| **Skalierung** | Milliarden von Zeilen |

**Vorteile für Solar:**
- **Hypertables:** Automatische Partitionierung nach Zeit
- **Continuous Aggregates:** Voraggregierte stündliche/tägliche Werte
- **Kompression:** 90%+ Speicherreduktion für historische Daten
- **Retention Policies:** Automatisches Löschen alter Rohdaten
- **Time-series Functions:** `time_bucket()`, `first()`, `last()`, `interpolate`

**Schema-Beispiel:**
```sql
-- Hypertable erstellen
CREATE TABLE weather_data (
    time TIMESTAMPTZ NOT NULL,
    location_id TEXT NOT NULL,
    temp_air DOUBLE PRECISION,
    ghi DOUBLE PRECISION,
    dni DOUBLE PRECISION,
    dhi DOUBLE PRECISION,
    cloud_cover DOUBLE PRECISION,
    wind_speed DOUBLE PRECISION
);

SELECT create_hypertable('weather_data', 'time');

-- Continuous Aggregate (stündlich)
CREATE MATERIALIZED VIEW weather_hourly
WITH (timescaledb.continuous) AS
SELECT time_bucket('1 hour', time) AS hour,
       location_id,
       AVG(ghi) AS avg_ghi,
       MAX(ghi) AS max_ghi,
       AVG(temp_air) AS avg_temp
FROM weather_data
GROUP BY hour, location_id;

-- Kompression aktivieren
ALTER TABLE weather_data SET (
    timescaledb.compress,
    timescaledb.compress_segmentby = 'location_id'
);
SELECT add_compression_policy('weather_data', INTERVAL '7 days');

-- Retention Policy (Rohdaten nach 1 Jahr löschen)
SELECT add_retention_policy('weather_data', INTERVAL '365 days');
```

### 8.4 Vergleich: SQLite vs. PostgreSQL vs. TimescaleDB

| Kriterium | SQLite | PostgreSQL | TimescaleDB |
|---|---|---|---|
| **Setup-Aufwand** | Keiner | Mittel (Docker) | Mittel (Docker) |
| **Skalierung** | ~1M Zeilen | Unbegrenzt | Unbegrenzt |
| **Zeitreihen-Features** | Keine | Basis | Exzellent |
| **Kompression** | Keine | Keine | 90%+ |
| **Aggregationen** | SQL | SQL | Continuous Aggregates |
| **Backup** | Datei kopieren | pg_dump | pg_dump |
| **Empfehlung** | Privat, <1M Zeilen | Mittel, Multi-User | Produktion, Zeitreihen |

### 8.5 Weitere Optionen

| Datenbank | Beschreibung | Einsatz |
|---|---|---|
| **InfluxDB** | Zeitreihen-DB (Open Source) | IoT, Monitoring |
| **DuckDB** | Analytische DB (in-process) | Ad-hoc-Analysen, ML-Training |
| **Parquet-Dateien** | Spaltenbasiert, komprimiert | ML-Training, Archiv |
| **Redis** | In-Memory Cache | Real-time Caching |
| **HDF5** | Hierarchisches Format | Wissenschaftliche Daten |

**Empfehlung für ML-Training:**
- **Rohdaten:** TimescaleDB/PostgreSQL (oder SQLite für kleinere Projekte)
- **ML-Training:** DuckDB oder Parquet-Dateien (schnelle analytische Queries)
- **Modell-Serving:** SQLite oder Redis (schneller Lookup)

---

## 9. Zusammenfassung und Empfehlungs-Matrix

### 9.1 Empfohlener Stack für private Solarprognosen

```
┌─────────────────────────────────────────────────────────────┐
│                    Datenquellen                              │
├─────────────────────────────────────────────────────────────┤
│  Wetter:     Open-Meteo (kostenlos, kein Key)               │
│  Strahlung:  Open-Meteo + CAMS (pvlib)                      │
│  PV-Daten:   PVOutput.org (Community) + eigene Anlage       │
│  Satellit:   Open-Meteo Satellite Radiation API              │
└─────────────────────────────────────────────────────────────┘
                            │
                            ▼
┌─────────────────────────────────────────────────────────────┐
│                    Pipeline (Cron + Python)                  │
├─────────────────────────────────────────────────────────────┤
│  1. Fetch:   Open-Meteo API → Rohdaten                      │
│  2. Transform: pvlib → Features (Solarpos, Clear-Sky, etc.) │
│  3. Store:   SQLite (oder TimescaleDB bei >1M Zeilen)       │
│  4. Train:   scikit-learn / XGBoost / LightGBM             │
│  5. Serve:   FastAPI / Flask → Prognose-API                 │
└─────────────────────────────────────────────────────────────┘
```

### 9.2 Kostenloser Stack (Minimal)

| Komponente | Tool | Kosten |
|---|---|---|
| Wetter-API | Open-Meteo | 0 € |
| Strahlung | Open-Meteo + pvlib | 0 € |
| PV-Daten | PVOutput.org | 0 € |
| Feature Eng. | pvlib Python | 0 € |
| ML-Modell | scikit-learn / XGBoost | 0 € |
| Datenbank | SQLite | 0 € |
| Pipeline | Cron + Python | 0 € |
| Monitoring | Grafana (optional) | 0 € |

### 9.3 Feature-Priorität für ML-Modelle

| Priorität | Feature | Begründung |
|---|---|---|
| ★★★★★ | Clear-Sky Index (Kt) | Stärkster Prädiktor |
| ★★★★★ | Solar Zenith/Azimuth | Physikalische Grundlage |
| ★★★★☆ | GHI/DNI/DHI (Forecast) | Direkte Strahlung |
| ★★★★☆ | Cloud Cover | Wolken = Hauptunsicherheit |
| ★★★☆☆ | Temperatur (Luft/Modul) | Temperaturkoeffizient |
| ★★★☆☆ | Wind Speed | Kühlungseffekt |
| ★★★☆☆ | Lag-Features (1h, 24h) | Zeitliche Autokorrelation |
| ★★☆☆☆ | Humidity | Indirekter Effekt |
| ★★☆☆☆ | Aerosol Optical Depth | Feinstaub-Effekt |
| ★★☆☆☆ | Soiling | Langfristiger Effekt |

### 9.4 Nächste Schritte

1. **Open-Meteo testen:** API-Calls für eigenen Standort durchführen
2. **pvlib installieren:** `pip install pvlib pandas numpy`
3. **Daten sammeln:** 1–2 Monate historische Daten + eigene PV-Daten
4. **Baseline-Modell:** Persistenz-Modell (morgen = heute) als Baseline
5. **ML-Modell:** XGBoost/LightGBM mit Clear-Sky Index als Hauptfeature
6. **Validierung:** RMSE, MAE, Skill Score vs. Clear-Sky-Modell
7. **Deployment:** Cron + SQLite + FastAPI

---

## Quellen und Referenzen

- Open-Meteo: https://open-meteo.com
- pvlib Python: https://pvlib-python.readthedocs.io
- PVOutput.org: https://pvoutput.org
- CAMS Solar: https://atmosphere.copernicus.eu/solar-energy
- ERA5: https://cds.climate.copernicus.eu
- DWD Open Data: https://opendata.dwd.de
- TimescaleDB: https://www.tigerdata.com/timescaledb
- Prefect: https://www.prefect.io
- Oil Price API (Feature Engineering): https://www.oilpriceapi.com/blog/feature-engineering-for-solar-energy-data