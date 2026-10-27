/* Adaptive Solar learning diagnostics. GPL-3.0-only. No network or state writes. */
const LEADS = ['0-6h', '6-24h', '24-48h', '48-96h', '96h+'];
const REASONS = {
  missing_energy_source: 'Kein Energiezähler gebunden',
  invalid_or_unavailable_energy_source: 'Energiequelle fehlt, ist zu alt oder ungültig',
  no_completed_archived_forecast_targets: 'Noch keine abgeschlossenen Prognoseziele',
  no_whole_measurement_inside_target: 'Kein vollständiges Messstück im Prognoseziel',
  insufficient_measurement_coverage: 'Messabdeckung zu gering',
  measurement_edge_exceeded: 'Messlücke am Intervallrand zu groß',
  insufficient_measured_duration: 'Gemessene Dauer zu kurz',
  internal_measurement_gap: 'Lücke innerhalb des Messintervalls',
  issued_after_target_start: 'Prognose erst nach Zielbeginn ausgegeben',
  target_shorter_than_minimum: 'Zielintervall kürzer als 30 Minuten',
  source_partial_at_issue: 'Wetterintervall bei Ausgabe bereits angeschnitten',
  stale_beam_shade_baseline: 'Archivierte Schattenbaseline nicht mehr kompatibel',
  low_elevation: 'Sonne zu niedrig', low_clearness: 'Nicht klar genug für Schattenaufnahme',
  stale_or_unpaired: 'Leistung und GHI zu alt oder nicht zeitlich gepaart',
  low_beam: 'Direktstrahlanteil zu gering', at_cap: 'Leistung nahe der Ausgangsgrenze',
  curtailed_or_invalid: 'Abgeregelt oder Messquelle ungültig',
  no_reference: 'Keine passende Wetterreferenz', insufficient_samples: 'Noch zu wenige Aufnahmen',
};
const STATES = {
  insufficient_history: 'Sammelt Daten', active: 'Intern validiert',
  rejected_validation: 'Prüfung nicht bestanden', insufficient_lead_validation: 'Horizonte noch nicht validiert',
  insufficient_validation: 'Noch nicht validiert', physics: 'Physik', mixed: 'Teilweise ML',
  complete: 'ML angewandt', partial: 'Prognoselücke', degraded: 'Eingang eingeschränkt',
  curtailed: 'Abregelung', unavailable: 'Nicht verfügbar', unknown: 'Unbekannt',
};
export const object = value => value && typeof value === 'object' && !Array.isArray(value) ? value : {};
export const number = value => typeof value === 'number' && Number.isFinite(value) ? value : null;
const count = value => number(value) !== null && value >= 0 ? value : null;
export const escapeHtml = value => String(value ?? '').replace(/[&<>"']/g, c => ({
  '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;',
}[c]));
const fmt = (value, digits = 0) => number(value) === null ? '—' : value.toLocaleString('de-DE', {
  minimumFractionDigits: digits, maximumFractionDigits: digits,
});
const stateName = value => STATES[value] || value || 'Noch kein Bericht';
const reasonName = value => REASONS[value] || value;
export const skill = report => {
  const base = count(report.physics_validation_mae_w), model = count(report.residual_validation_mae_w);
  return base !== null && base > 0 && model !== null ? (1 - model / base) * 100 : null;
};
export function readPlant(hass, config, now = Date.now()) {
  const entity = object(hass?.states?.[config.entity]);
  const attrs = object(entity.attributes), learning = object(attrs.learning);
  const ids = Object.keys(learning);
  const id = config.stage_id || (ids.length === 1 ? ids[0] : null);
  const report = object(id ? learning[id] : null), quality = object(report.training_quality);
  const meter = object(quality.meter), alignment = object(quality.alignment);
  const unavailable = !entity.state || ['unavailable', 'unknown'].includes(entity.state);
  const stamp = typeof attrs.issued_at === 'string' ? Date.parse(attrs.issued_at) : NaN;
  return { name: config.name || 'Ausgangsstufe', entityId: config.entity, entity,
    report, meter, alignment, regimes: object(report.regimes), shade: object(report.beam_shade),
    inputs: object(attrs.inputs), issuedAt: Number.isFinite(stamp) ? stamp : null,
    stale: !Number.isFinite(stamp) || now - stamp > 15 * 60000 || stamp - now > 60000,
    unavailable, ambiguous: !config.stage_id && ids.length > 1, timezone: hass?.config?.time_zone || 'UTC',
    missingMeter: meter.energy_source === 'not_configured',
  };
}
const pill = (text, tone = '') => `<span class="pill ${tone}">${escapeHtml(text)}</span>`;
const stat = (label, value) => `<div class="stat"><strong>${escapeHtml(value)}</strong><span>${escapeHtml(label)}</span></div>`;
function progress(label, value, threshold, unit, tone = 'blue') {
  const n = count(value), pct = n === null ? null : Math.min(100, n / threshold * 100);
  return `<div class="progress"><div class="line"><span>${escapeHtml(label)}</span><strong>${fmt(n)} / ${threshold} ${unit}</strong></div>
    <div class="track ${tone}" ${pct === null ? '' : `role="progressbar" aria-label="${escapeHtml(label)}" aria-valuenow="${n}" aria-valuemin="0" aria-valuemax="${Math.max(n, threshold)}"`}>
    ${pct === null ? '<span class="missing">Keine auswertbare Historie</span>' : `<i style="width:${pct}%"></i>`}</div></div>`;
}
function errorChart(report) {
  const base = count(report.physics_validation_mae_w), model = count(report.residual_validation_mae_w);
  if (base === null || model === null) return '<p class="muted">Modellgüte noch nicht bewertbar · unabhängige Prüfdaten fehlen.</p>';
  const max = Math.max(base, model, 1), delta = skill(report);
  return `<div class="error-chart" aria-label="Mittlerer absoluter Fehler auf unabhängigen Prüftagen">
    <div class="error-row"><span>Physik</span><div class="track"><i class="baseline" style="width:${base / max * 100}%"></i></div><strong>${fmt(base)} W</strong></div>
    <div class="error-row"><span>Mit ML</span><div class="track"><i style="width:${model / max * 100}%"></i></div><strong>${fmt(model)} W</strong></div></div>
    <p class="metric">Fehlerreduktion <strong class="${delta !== null && delta > 5 ? 'good' : 'warn'}">${fmt(delta, 1)} %</strong> · gewonnene Prüftage <strong>${fmt(number(report.validation_daily_win_fraction) === null ? null : report.validation_daily_win_fraction * 100, 1)} %</strong></p>`;
}
function leadTable(report) {
  const bins = object(report.lead_bins);
  if (!Object.keys(bins).length) return '';
  return `<div class="scroll"><table><thead><tr><th>Vorlauf</th><th>Freigabe</th><th>Fehler ↓</th><th>Gewinntage</th><th>Fehlerband ±</th></tr></thead><tbody>${LEADS.map(key => {
    const b = object(bins[key]);
    const supported = number(b.supported_lead_min_hours) !== null && number(b.supported_lead_max_hours) !== null
      ? `${fmt(b.supported_lead_min_hours, 1)}–${fmt(b.supported_lead_max_hours, 1)} h` : '—';
    return `<tr><th>${escapeHtml(key)}</th><td>${escapeHtml(stateName(b.state))}<small>${supported}</small></td><td>${fmt(skill(b), 1)} %</td><td>${fmt(number(b.validation_daily_win_fraction) === null ? null : b.validation_daily_win_fraction * 100, 1)} %</td><td>${fmt(count(b.calibration_radius_w))} W</td></tr>`;
  }).join('')}</tbody></table></div>`;
}
function regimePanel(name, report) {
  const r = object(report);
  return `<section class="regime"><div class="line"><h3>${name === 'nwp' ? 'NWP · Wettermodell' : 'GHI · lokale Einstrahlung'}</h3>${pill(stateName(r.state), r.state === 'active' ? 'green' : '')}</div>
    ${progress('Qualifizierte Zieltage', r.target_days, 28, 'Tage')}${progress('Eindeutige Messdauer', r.unique_target_hours, 240, 'h')}
    ${errorChart(r)}${leadTable(r)}</section>`;
}
function statusNotice(p) {
  if (p.ambiguous) return '<p class="notice">Mehrere Stufen gefunden · bitte die gewünschte Stufenkennung konfigurieren.</p>';
  if (p.unavailable) return '<p class="notice">Quelle nicht verfügbar · angezeigte Attribute sind gegebenenfalls der letzte bekannte Stand.</p>';
  if (p.stale) return '<p class="notice">Kein aktueller Ausgabestand · Lernwerte nicht als aktuellen Zustand bewerten.</p>';
  return '';
}
export function renderOverview(plants) {
  const current = plants.filter(p => !p.unavailable && !p.stale && !p.ambiguous);
  const active = current.filter(p => Object.values(p.regimes).some(r => object(r).state === 'active')).length;
  const blocked = plants.filter(p => p.missingMeter || p.unavailable || p.stale || (Array.isArray(p.report.training_quality?.blocking_reasons) && p.report.training_quality.blocking_reasons.length)).length;
  const released = current.length === plants.length && current.every(p => count(p.shade.filled_bins) !== null)
    ? current.reduce((sum, p) => sum + p.shade.filled_bins, 0) : null;
  return `<h2>Lernen im Überblick</h2><div class="summary">${stat('Aktuelle Anlagen mit intern validiertem ML', current.length ? `${active} / ${current.length}` : '—')}${stat('Anlagen mit Datenhinweisen', blocked)}${stat('Freigegebene Schattenfenster¹', fmt(released))}</div>
    <div class="overview-list">${plants.map(p => {
      const states = Object.values(p.regimes).map(r => object(r).state);
      const text = p.unavailable ? 'Quelle nicht verfügbar' : p.stale ? 'Stand veraltet' : p.missingMeter ? 'Energiequelle fehlt' : states.includes('active') ? 'ML intern validiert' : 'Lernhistorie im Aufbau';
      return `<div class="overview-row"><strong>${escapeHtml(p.name)}</strong>${pill(text, p.missingMeter || p.unavailable || p.stale ? 'amber' : states.includes('active') ? 'green' : '')}<span>${fmt(count(p.alignment.accepted_target_cells))} / ${fmt(count(p.alignment.completed_target_cells))} Ziele angenommen</span></div>`;
    }).join('')}</div><p class="muted footnote">${current.length} von ${plants.length} Anlagen mit aktuellem Stand. Mindesthistorie und interne Validierung sind getrennte Schritte. ¹ Anzahl gespeicherter Fenster, kein Prozentwert für Prognosegenauigkeit.</p>`;
}
export function renderPlant(p) {
  const accepted = count(p.alignment.accepted_target_cells), rejected = count(p.alignment.rejected_target_cells);
  const reasons = object(p.alignment.rejection_reasons);
  const shade = p.shade, released = shade.released === true;
  const shadeReasons = typeof shade.last_rejection === 'string' ? shade.last_rejection.split(';').filter(Boolean) : [];
  const stamp = p.issuedAt === null ? 'unbekannt' : new Intl.DateTimeFormat('de-DE', { dateStyle: 'short', timeStyle: 'short', timeZone: p.timezone }).format(p.issuedAt);
  const meterStatus = {not_configured: 'Nicht gebunden', valid_reported_state: 'Aktueller Zählerbericht', missing_stale_restored_or_invalid: 'Fehlt, veraltet oder ungültig', awaiting_report_after_measurement_valid: 'Wartet auf neuen Originalbericht', blocked_measurement_invalid_or_not_monitored: 'Messung gesperrt'};
  return `<div class="line"><h2>${escapeHtml(p.name)}</h2>${pill(stateName(p.entity.state))}</div><p class="stamp">Prognosestand ${escapeHtml(stamp)} · verfügbare PV-Leistung</p>${statusNotice(p)}
    ${p.missingMeter ? '<p class="notice">Ohne gebundenen Energiezähler entstehen keine Lernlabels für das Residualmodell. Schattenlernen aus Leistung und GHI bleibt davon unabhängig.</p>' : ''}
    <div class="summary compact">${stat('Ziele angenommen', fmt(accepted))}${stat('Ziele abgelehnt', fmt(rejected))}${stat('Noch nicht abgeschlossen', fmt(count(p.alignment.pending_target_cells)))}</div>
    ${regimePanel('nwp', p.regimes.nwp)}${regimePanel('ghi', p.regimes.ghi)}
    <p class="muted small">Standard-Mindesthistorie je Regime: 28 Tage + 240 h. Danach: &gt;5 % weniger Fehler und ≥60 % gewonnene Prüftage; zusätzliche Horizont- und Kalibrierungsprüfungen.</p>
    <section class="shade"><div class="line"><h3>Direktstrahl-Schattenlernen</h3>${pill(`${fmt(count(shade.filled_bins))} Fenster freigegeben`, 'purple')}</div>
      <div class="shade-numbers">${stat('Aktuelles Sonnenfenster', number(shade.azimuth_bin_deg) !== null && number(shade.elevation_bin_deg) !== null ? `${fmt(shade.azimuth_bin_deg)}° / ${fmt(shade.elevation_bin_deg)}°` : '—')}${stat(released ? 'Gelernter Direktlicht-Durchlass' : 'Aktuelle Korrektur', released && number(shade.transmittance) !== null ? `${fmt(shade.transmittance * 100)} %` : 'Noch neutral')}</div>
      ${progress('Aufnahmen im aktuellen Fenster', shade.samples, 5, 'zur Freigabe', 'purple')}
      ${shadeReasons.length ? `<p class="muted small">${shadeReasons.map(reasonName).map(escapeHtml).join(' · ')}</p>` : ''}
      <p class="muted small">Median ab 5 verschiedenen UTC-Viertelstunden; bis zu 24 je Fenster. Der Faktor betrifft nur Direktlicht und ist keine Genauigkeitskennzahl.</p></section>
    <details data-key="quality"><summary>Messqualität und Lernhindernisse</summary><p class="metric">Energiequelle: <strong>${escapeHtml(meterStatus[p.meter.energy_source] || p.meter.energy_source || 'Kein Bericht')}</strong></p>
      ${Object.keys(reasons).length ? `<ul>${Object.entries(reasons).map(([key, n]) => `<li>${escapeHtml(reasonName(key))}: <strong>${fmt(count(n))}</strong></li>`).join('')}</ul><p class="muted small">Gründe können dieselbe Zielzelle mehrfach betreffen und werden nicht addiert.</p>` : '<p class="muted">Keine Alignment-Ablehnungsgründe gemeldet.</p>'}
      <p class="metric">Archivierte Messstücke: ${fmt(count(p.alignment.stored_measurement_intervals))} · angenommene Messdauer: ${fmt(number(p.alignment.accepted_unique_measured_seconds) === null ? null : p.alignment.accepted_unique_measured_seconds / 3600, 2)} h</p>
      <p class="muted small">Messstücke sind keine unabhängigen Trainingsstunden. Ereigniszähler und mehrere Prognoseausgaben erhöhen die eindeutige Messdauer nicht.</p></details>`;
}
const CSS = `
:host{display:block;color:var(--primary-text-color);font-family:var(--paper-font-body1_-_font-family,Roboto,sans-serif)}
ha-card{overflow:hidden}article{padding:20px}h2{font-size:20px;font-weight:600;margin:0 0 6px}h3{font-size:14px;margin:0;font-weight:600}.line{display:flex;align-items:center;justify-content:space-between;gap:8px;flex-wrap:wrap}.line>h2{margin:0}.pill{font-size:11px;padding:4px 9px;border-radius:20px;background:var(--secondary-background-color,#eee);color:var(--primary-text-color);font-weight:500;white-space:normal}.green{background:#d9f2df;color:#175d2d}.amber{background:#fff0d4;color:#80500b}.purple.pill{background:#ede3fa;color:#5e3686}.summary{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:14px;margin:18px 0}.stat{min-width:0}.stat strong{display:block;font-size:26px;line-height:1.25;font-variant-numeric:tabular-nums}.stat span{display:block;font-size:12px;color:var(--secondary-text-color);margin-top:4px;line-height:1.35}.compact .stat strong{font-size:23px}.muted,.stamp{color:var(--secondary-text-color);font-size:12px;line-height:1.5}.stamp{margin:7px 0 14px}.small{font-size:11px}.regime{margin-top:14px;padding:14px 0 0;border-top:1px solid var(--divider-color,#ddd)}.regime .line{margin-bottom:10px}.progress{margin:10px 0}.progress .line{font-size:12px;margin-bottom:5px}.progress strong{font-variant-numeric:tabular-nums}.track{height:8px;background:var(--secondary-background-color,#eee);border-radius:5px;overflow:hidden;position:relative}.track i{display:block;height:100%;background:#2c8ac7;border-radius:5px;min-width:0}.track.purple i{background:#8c64b0}.track:has(.missing){height:18px;background:repeating-linear-gradient(135deg,transparent,transparent 4px,var(--divider-color,#eee) 4px,var(--divider-color,#eee) 5px)}.missing{font-size:10px;color:var(--secondary-text-color);padding-left:6px}.metric{font-size:12px;line-height:1.5}.good{color:var(--success-color,#2a824a)}.warn{color:var(--warning-color,#b77a13)}.error-chart{margin:12px 0}.error-row{display:grid;grid-template-columns:48px 1fr 70px;gap:8px;align-items:center;font-size:12px;margin:7px 0}.error-row strong{text-align:right;font-variant-numeric:tabular-nums}.track i.baseline{background:#8999a3}.shade{border-top:1px solid var(--divider-color,#ddd);margin-top:16px;padding-top:16px}.shade-numbers{display:grid;grid-template-columns:1fr 1fr;gap:16px;margin:12px 0}.shade-numbers .stat strong{font-size:19px}.notice{background:var(--secondary-background-color,#f5f5f5);border-left:3px solid #df9a2a;padding:10px;font-size:12px;line-height:1.5}.overview-row{display:grid;grid-template-columns:minmax(80px,1fr) minmax(120px,1.4fr) minmax(120px,1fr);gap:10px;align-items:center;padding:10px 0;border-top:1px solid var(--divider-color,#ddd);font-size:13px}.overview-row>span:last-child{text-align:right;color:var(--secondary-text-color);font-size:12px}.footnote{margin-bottom:0}.scroll{overflow-x:auto}table{border-collapse:collapse;width:100%;font-size:11px;margin:8px 0}th,td{padding:7px 5px;text-align:right;border-bottom:1px solid var(--divider-color,#ddd);white-space:nowrap}th:first-child{text-align:left}td small{display:block;color:var(--secondary-text-color)}details{border-top:1px solid var(--divider-color,#ddd);padding-top:12px;margin-top:14px;font-size:12px}summary{cursor:pointer;font-weight:500}li{margin:6px 0}button{border:0;background:none;color:var(--primary-color,#1976d2);padding:12px 0 0;font:inherit;font-size:12px;cursor:pointer}
@media(max-width:500px){article{padding:16px}.summary{gap:8px}.stat strong{font-size:23px}.overview-row{grid-template-columns:1fr auto}.overview-row>span:last-child{grid-column:1/-1;text-align:left}h2{font-size:18px}.shade-numbers .stat strong{font-size:17px}}
`;
export class AdaptiveSolarLearningCard extends (globalThis.HTMLElement || class {}) {
  constructor() { super(); this.attachShadow?.({mode:'open'}); }
  connectedCallback() {
    if (!this._timer) this._timer = setInterval(() => {if (this._hass) this.hass = this._hass;}, 60000);
  }
  disconnectedCallback() { clearInterval(this._timer); this._timer = null; }
  setConfig(config) {
    if (!['plant','overview'].includes(config.mode || 'plant')) throw Error('mode muss plant oder overview sein');
    if (config.mode === 'overview') {
      if (!Array.isArray(config.plants) || !config.plants.length || config.plants.some(p => !p.entity)) throw Error('plants mit entity erforderlich');
    } else if (!config.entity) throw Error('entity erforderlich');
    this._config = {...config}; this._refs = null; if (this._hass) this.hass = this._hass;
  }
  set hass(hass) {
    this._hass = hass;
    if (!this._config || !this.shadowRoot) return;
    const configs = this._config.mode === 'overview' ? this._config.plants : [this._config];
    const refs = configs.map(c => hass.states[c.entity]);
    const minute = Math.floor(Date.now() / 60000);
    if (this._refs && this._minute === minute && refs.every((r,i) => r === this._refs[i])) return;
    this._minute = minute;
    this._refs = refs;
    const open = new Set([...this.shadowRoot.querySelectorAll('details[open]')].map(el => el.dataset.key));
    const plants = configs.map(c => readPlant(hass,c));
    this.shadowRoot.innerHTML = `<style>${CSS}</style><ha-card><article>${this._config.mode === 'overview' ? renderOverview(plants) : renderPlant(plants[0])}${this._config.mode === 'overview' ? '' : '<button type="button">Original-Lernstatus öffnen</button>'}</article></ha-card>`;
    this.shadowRoot.querySelectorAll('details').forEach(el => {el.open = open.has(el.dataset.key);});
    this.shadowRoot.querySelector('button')?.addEventListener('click', () => this.dispatchEvent(new CustomEvent('hass-more-info', {detail:{entityId:this._config.entity},bubbles:true,composed:true})));
  }
  getCardSize() { return this._config?.mode === 'overview' ? 5 : 11; }
  getGridOptions() { return {columns:12,rows:'auto',min_columns:6}; }
}
if (globalThis.customElements && !customElements.get('adaptive-solar-learning-card')) {
  customElements.define('adaptive-solar-learning-card',AdaptiveSolarLearningCard);
  window.customCards = window.customCards || [];
  window.customCards.push({type:'adaptive-solar-learning-card',name:'Adaptive Solar Lernstatus',description:'Lernhistorie, interne Modellgüte, Messqualität und Direktstrahl-Verschattung.'});
}
