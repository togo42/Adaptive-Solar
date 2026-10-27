import assert from 'node:assert/strict';
import {readFile} from 'node:fs/promises';
import test from 'node:test';
const source = await readFile(new URL('../../examples/lovelace/adaptive-solar-learning-card.js', import.meta.url), 'utf8');
const {readPlant, renderPlant, renderOverview, skill, escapeHtml, AdaptiveSolarLearningCard} = await import(`data:text/javascript;base64,${Buffer.from(source).toString('base64')}`);
const config = {entity:'sensor.example_quality',name:'Beispiel',stage_id:'example'};
const now = Date.parse('2026-06-01T10:00:00Z');
const report = {state:'insufficient_history',regimes:{nwp:{state:'insufficient_history',target_days:7,unique_target_hours:42},ghi:{state:'insufficient_history',target_days:2,unique_target_hours:8}},beam_shade:{filled_bins:0,samples:2,released:false,transmittance:1,azimuth_bin_deg:180,elevation_bin_deg:40},training_quality:{meter:{energy_source:'valid_reported_state'},alignment:{completed_target_cells:10,accepted_target_cells:8,rejected_target_cells:2,pending_target_cells:3,accepted_unique_measured_seconds:14400,stored_measurement_intervals:50,rejection_reasons:{internal_measurement_gap:2,insufficient_measurement_coverage:2}}}};
function fixture(value=report,state='physics') {
  return {config:{time_zone:'Europe/Berlin'},states:{[config.entity]:{state,attributes:{issued_at:'2026-06-01T09:59:00Z',learning:{example:structuredClone(value)}}}}};
}
test('regime progress uses its own history, never flattened global counters',()=>{
  const value={...report,target_days:99,unique_target_hours:999};
  const html=renderPlant(readPlant(fixture(value),config,now));
  assert.match(html,/7 \/ 28 Tage/); assert.match(html,/2 \/ 28 Tage/);
  assert.match(html,/42 \/ 240 h/); assert.match(html,/8 \/ 240 h/);
  assert.doesNotMatch(html,/99 \/ 28|999 \/ 240/);
});
test('cold start leaves absent metrics missing, including model error',()=>{
  const html=renderPlant(readPlant(fixture({state:'insufficient_history'}),config,now));
  assert.match(html,/— \/ 28 Tage/); assert.match(html,/Modellgüte noch nicht bewertbar/);
  assert.doesNotMatch(html,/0 W|NaN|undefined|Infinity/);
});
test('error reduction preserves zero error and negative improvement without dividing by zero',()=>{
  assert.ok(Math.abs(skill({physics_validation_mae_w:500,residual_validation_mae_w:400})-20)<1e-10);
  assert.ok(Math.abs(skill({physics_validation_mae_w:500,residual_validation_mae_w:600})+20)<1e-10);
  assert.equal(skill({physics_validation_mae_w:0,residual_validation_mae_w:0}),null);
  assert.equal(skill({physics_validation_mae_w:500,residual_validation_mae_w:0}),100);
  for(const invalid of [null,true,'0',Infinity,NaN]) assert.equal(skill({physics_validation_mae_w:500,residual_validation_mae_w:invalid}),null);
});
test('validated metrics and lead ranges are shown per regime',()=>{
  const value=structuredClone(report);
  value.regimes.nwp={state:'active',target_days:30,unique_target_hours:250,physics_validation_mae_w:500,residual_validation_mae_w:400,validation_daily_win_fraction:.7,lead_bins:{'0-6h':{state:'active',supported_lead_min_hours:1,supported_lead_max_hours:4,physics_validation_mae_w:500,residual_validation_mae_w:400,validation_daily_win_fraction:.75,calibration_radius_w:0}}};
  const html=renderPlant(readPlant(fixture(value),config,now));
  assert.match(html,/500 W/); assert.match(html,/400 W/);assert.match(html,/20,0 %/);assert.match(html,/70,0 %/);
  assert.match(html,/1,0–4,0 h/);assert.match(html,/>0 W</);
});
test('shading release and attenuation do not imply accuracy or completed residual training',()=>{
  const value=structuredClone(report);value.beam_shade={filled_bins:2,samples:6,released:true,transmittance:.65,azimuth_bin_deg:180,elevation_bin_deg:40};
  const html=renderPlant(readPlant(fixture(value),config,now));
  assert.match(html,/65 %/);assert.match(html,/2 Fenster freigegeben/);assert.match(html,/6 \/ 5 zur Freigabe/);
  assert.match(html,/keine Genauigkeitskennzahl/);assert.match(html,/Modellgüte noch nicht bewertbar/);
});
test('missing meter blocks residual labels but does not label shading as impossible',()=>{
  const value=structuredClone(report);value.training_quality.meter.energy_source='not_configured';
  const p=readPlant(fixture(value),config,now);
  assert.equal(p.missingMeter,true);assert.match(renderPlant(p),/Schattenlernen.*unabhängig/);
  assert.match(renderOverview([p]),/Energiequelle fehlt/);
});
test('overlapping rejection reasons retain individual counts and do not become a summed rejection rate',()=>{
  const html=renderPlant(readPlant(fixture(),config,now));
  assert.match(html,/Ziele abgelehnt/);assert.match(html,/nicht addiert/);assert.match(html,/Lücke innerhalb/);
});
test('unavailable and stale sources cannot advertise active ML or complete shade totals',()=>{
  const value=structuredClone(report);value.regimes.nwp.state='active';value.beam_shade.filled_bins=9;
  const missing=readPlant(fixture(value,'unavailable'),config,now);
  const stale=readPlant(fixture(value),config,now+20*60000);
  for(const p of [missing,stale]) {
    const html=renderOverview([p]);
    assert.match(html,/0 von 1 Anlagen mit aktuellem Stand/);assert.doesNotMatch(html,/>9</);
    assert.match(renderPlant(p),/letzte bekannte Stand|Kein aktueller/);
  }
});
test('multi-stage source requires an explicit stage id',()=>{
  const hass=fixture();hass.states[config.entity].attributes.learning.second={state:'active'};
  const p=readPlant(hass,{entity:config.entity,name:'Beispiel'},now);
  assert.equal(p.ambiguous,true);assert.match(renderPlant(p),/Mehrere Stufen gefunden/);
});
test('entity labels, backend status and unknown rejection reasons are escaped',()=>{
  const value=structuredClone(report);value.training_quality.alignment.rejection_reasons={'<img src=x onerror=alert(1)>':1};
  const p=readPlant(fixture(value),{...config,name:'<script>bad</script>'},now);
  const html=renderPlant(p);assert.doesNotMatch(html,/<script>|<img /);assert.match(html,/&lt;script&gt;/);
  assert.equal(escapeHtml('"&'), '&quot;&amp;');
});
test('missing and future issue timestamps are not current',()=>{
  const hass=fixture();delete hass.states[config.entity].attributes.issued_at;
  assert.equal(readPlant(hass,config,now).stale,true);
  hass.states[config.entity].attributes.issued_at='2026-06-01T11:00:00Z';
  assert.equal(readPlant(hass,config,now).stale,true);
});
test('card validates configuration without registering helpers or calling services',()=>{
  const card=new AdaptiveSolarLearningCard();
  assert.throws(()=>card.setConfig({}),/entity erforderlich/);
  assert.throws(()=>card.setConfig({mode:'overview',plants:[]}),/plants/);
  assert.throws(()=>card.setConfig({mode:'bad',entity:config.entity}),/mode/);
  card.setConfig(config);assert.equal(card.getGridOptions().rows,'auto');
  assert.doesNotMatch(source,/fetch\(|callService\(|callWS\(/);
});
