"""Native HA integral + quality template + original reports, no provider I/O.

30s is a synthetic test parameter, not a deployment freshness recommendation.
RAW last_reported is read only by the quality template; its10s timer never
republishes energy. Real left/max_sub_interval5min integration owns energy.
"""
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock

from freezegun import freeze_time
from homeassistant.core import callback
from homeassistant.helpers.event import async_track_state_change_event, async_track_state_report_event
from homeassistant.setup import async_setup_component
from pytest_homeassistant_custom_component.common import MockConfigEntry, async_fire_time_changed_exact
import pytest

from custom_components.adaptive_solar.coordinator import AdaptiveSolarCoordinator
from custom_components.adaptive_solar.core.models import InverterConfig, SiteConfig, StringConfig

START = datetime(2026, 6, 1, 10, tzinfo=UTC)
RAW = ('sensor.raw_l2', 'sensor.raw_l3')
POWER = 'sensor.native_sum'
ENERGY = 'sensor.native_integral'
FLAG = 'binary_sensor.native_measurement_valid'
ATTRS = {'unit_of_measurement': 'W', 'device_class': 'power', 'state_class': 'measurement'}


def quality_template(ids):
    return """{% set ok = namespace(value=trigger.id != 'startup') %}
{% for id in """ + repr(list(ids)) + """ %}
{% set s = states[id] %}
{% if s is none or not is_number(s.state) or s.state|float < 0
      or s.attributes.get('restored',false) or s.attributes.get('unit_of_measurement') != 'W' %}
{% set ok.value = false %}
{% else %}
{% set age = as_timestamp(now()) - as_timestamp(s.last_reported) %}
{% if age < 0 or age > 30 %}{% set ok.value = false %}{% endif %}
{% endif %}
{% endfor %}{{ ok.value }}"""


@dataclass
class NativePath:
    hass: object
    clock: object
    coordinator: object
    sources: tuple
    reports: list

    async def at(self, seconds, values=None):
        self.clock.move_to(START + timedelta(seconds=seconds))
        for entity, value in (values or {}).items():
            self.hass.states.async_set(entity, str(value), ATTRS)
        await self.hass.async_block_till_done()
        # Native timers are spread over the first500ms. Keep both UTC now and
        # callback time at the same instant; otherwise the helper's default
        # +500ms would add fictitious energy while reporting an earlier time.
        timer_time = START + timedelta(seconds=seconds, milliseconds=500)
        self.clock.move_to(timer_time)
        async_fire_time_changed_exact(self.hass, timer_time)
        await self.hass.async_block_till_done()

    def flag(self):
        return self.hass.states.get(FLAG).state

    def counter(self):
        return float(self.hass.states.get(ENERGY).state)

    def numeric_reports(self):
        return [(t, float(v)) for t, v in self.reports if v not in ('unknown', 'unavailable')]


@pytest.fixture
async def native_path(hass, request):
    sources = RAW if getattr(request, 'param', 'east') == 'east' else RAW[:1]
    with freeze_time(START) as clock:
        assert await async_setup_component(hass, 'homeassistant', {})
        for entity in sources:
            hass.states.async_set(entity, '1000', ATTRS)
        template = [
            {'sensor': [{'name': 'Native sum', 'unique_id': 'native_sum',
                         'unit_of_measurement': 'W', 'device_class': 'power', 'state_class': 'measurement',
                         'availability': '{{ ' + ' and '.join("is_number(states('" + s + "'))" for s in sources) + ' }}',
                         'state': '{{ ' + ' + '.join("states('" + s + "')|float" for s in sources) + ' }}'}]},
            {'triggers': [{'trigger': 'state', 'entity_id': list(sources), 'id': 'raw'},
                          {'trigger': 'time_pattern', 'seconds': '/10', 'id': 'age'},
                          {'trigger': 'homeassistant', 'event': 'start', 'id': 'startup'}],
             'binary_sensor': [{'name': 'Native measurement valid', 'unique_id': 'native_measurement_valid',
                                'state': quality_template(sources)}]},
        ]
        config_native = {'template': template, 'sensor': [{'platform': 'integration',
            'name': 'Native integral', 'unique_id': 'native_integral', 'source': POWER,
            'method': 'left', 'unit_prefix': 'k', 'unit_time': 'h', 'round': 9,
            'max_sub_interval': {'minutes': 5}}]}
        assert await async_setup_component(hass, 'sensor', config_native)
        assert await async_setup_component(hass, 'template', config_native)
        await hass.async_start()
        await hass.async_block_till_done()
        assert hass.states.get(POWER) is not None and hass.states.get(ENERGY) is not None
        config = SiteConfig(50, 8, 'Europe/Berlin', (StringConfig('s', 'i', 5, 30, 180),),
            (InverterConfig('i', 5, power_entity_id=POWER, energy_entity_id=ENERGY, measurement_valid_entity_id=FLAG),))
        entry = MockConfigEntry(domain='adaptive_solar', data={'site': config.to_dict()})
        entry.add_to_hass(hass)
        c = AdaptiveSolarCoordinator(hass, entry, config, AsyncMock())
        c.async_start_tracking()
        reports = []
        @callback
        def collect(event):
            state = event.data['new_state']
            reports.append((event.data.get('last_reported', state.last_updated), state.state))
        unsub = [async_track_state_change_event(hass, [ENERGY], collect),
                 async_track_state_report_event(hass, [ENERGY], collect)]
        yield NativePath(hass, clock, c, sources, reports)
        for remove in unsub:
            remove()
        await c.async_close()
        for trigger in hass.data['template']:
            await trigger.async_shutdown()
        await hass.data['sensor']._async_reset()
        await hass.data['binary_sensor']._async_reset()


@pytest.mark.parametrize('native_path', ['west', 'east'], indirect=True)
async def test_quality_timer_expires_held_source_without_creating_energy_reports(native_path):
    p = native_path
    await p.at(10, {s: 1000 for s in p.sources})
    assert p.flag() == 'on'
    before = list(p.reports)
    for seconds in (20, 30):
        await p.at(seconds)
    assert p.flag() == 'on'  # last_reported10 advanced despite unchanged value/last_updated0.
    for seconds in (40, 50):
        await p.at(seconds)
    assert p.flag() == 'off'
    assert p.reports == before and not p.coordinator.intervals
    assert 'i' not in p.coordinator.tracker.anchors
    assert not [o for o in p.coordinator._observations(START + timedelta(seconds=50)) if o.power_w is not None]


@pytest.mark.parametrize('stale_index', [0, 1])
async def test_one_stale_raw_phase_blocks_a_still_fresh_sum(native_path, stale_index):
    p = native_path
    stale, fresh = RAW[stale_index], RAW[1 - stale_index]
    for seconds in (10, 20, 30, 40, 50):
        await p.at(seconds, {fresh: 1000 + seconds})
    assert p.flag() == 'off'
    assert (START + timedelta(seconds=50) - p.hass.states.get(POWER).last_reported).total_seconds() == 0
    assert p.hass.states.get(stale).last_reported == START
    assert 'i' not in p.coordinator.tracker.anchors
    assert not [o for o in p.coordinator._observations(START + timedelta(seconds=50)) if o.power_w is not None]


@pytest.mark.parametrize('native_path', ['west', 'east'], indirect=True)
async def test_quality_on_before_pending_integral_flush_discards_old_energy_without_extra_wait(native_path):
    p = native_path
    await p.at(10, {p.sources[0]: 1100})
    for seconds in (20, 30, 40, 50):
        await p.at(seconds)
    assert p.flag() == 'off' and not p.coordinator.tracker.anchors
    before = len(p.numeric_reports())
    # Unchanged RAW reports do not republish the sum/energy. Quality can turn
    # on BEFORE pending native5minute flush, which includes invalid time.
    await p.at(60, {s: p.hass.states.get(s).state for s in p.sources})
    assert p.flag() == 'on' and len(p.numeric_reports()) == before
    assert not p.coordinator.tracker.anchors
    for seconds in range(70, 311, 10):
        await p.at(seconds, {s: p.hass.states.get(s).state for s in p.sources})
    first_time, first_value = p.numeric_reports()[-1]
    assert first_time == START + timedelta(seconds=310, milliseconds=500)
    assert first_time > p.coordinator._measurement_valid_since['i']
    assert p.coordinator.tracker.anchors['i'] == (first_time, first_value)
    assert not p.coordinator.intervals
    for seconds in range(320, 611, 10):
        await p.at(seconds, {s: p.hass.states.get(s).state for s in p.sources})
    assert len(p.coordinator.intervals) == 1
    accepted = p.coordinator.intervals[0]
    assert datetime.fromisoformat(accepted['start']) == first_time
    assert datetime.fromisoformat(accepted['end']) == START + timedelta(seconds=610, milliseconds=500)
    watts = sum(float(p.hass.states.get(s).state) for s in p.sources)
    assert accepted['energy_kwh'] == pytest.approx(watts * 300 / 3600000, abs=2e-9)
    assert accepted['energy_kwh'] == pytest.approx(p.counter() - first_value, abs=2e-9)


@pytest.mark.parametrize('native_path', ['west', 'east'], indirect=True)
async def test_real_zero_integral_reports_form_zero_label_but_quality_ticks_do_not(native_path):
    p = native_path
    await p.at(1, {s: 0 for s in p.sources})
    await p.at(10, {s: 0 for s in p.sources})
    start_reports = len(p.numeric_reports())
    for seconds in range(20, 301, 10):
        await p.at(seconds, {s: 0 for s in p.sources})
    assert len(p.numeric_reports()) == start_reports
    await p.at(301, {s: 0 for s in p.sources})
    first = p.coordinator.tracker.anchors['i']
    for seconds in range(310, 601, 10):
        await p.at(seconds, {s: 0 for s in p.sources})
    await p.at(601, {s: 0 for s in p.sources})
    assert p.flag() == 'on'
    assert p.coordinator.intervals[-1]['energy_kwh'] == 0
    assert p.coordinator.tracker.events['i']['accepted_zero_delta'] >= 1
    assert p.coordinator.tracker.anchors['i'][0] > first[0]
    assert len(p.numeric_reports()) == start_reports + 2


async def test_startup_restored_sources_remain_invalid_until_new_native_reports(native_path):
    p = native_path
    assert p.flag() == 'off' and not p.coordinator.tracker.anchors
    p.clock.move_to(START + timedelta(seconds=1))
    for source in p.sources:
        p.hass.states.async_set(source, '1000', {**ATTRS, 'restored': True})
    await p.hass.async_block_till_done()
    await p.at(10)
    assert p.flag() == 'off' and not p.coordinator.tracker.anchors
    await p.at(20, {s: 1000 for s in p.sources})
    assert p.flag() == 'on' and not p.coordinator.tracker.anchors
    assert not p.coordinator.intervals


@pytest.mark.parametrize('unavailable_sources', [RAW[1:], RAW])
async def test_native_unavailable_recovery_does_not_bridge_the_invalid_phase(native_path, unavailable_sources):
    p = native_path
    for second in (10, 20, 30):
        await p.at(second, {s: 1000 + second for s in p.sources})
    before = list(p.coordinator.intervals)
    await p.at(40, {s: 'unavailable' for s in unavailable_sources})
    assert p.flag() == 'off' and p.hass.states.get(ENERGY).state == 'unavailable'
    assert not p.coordinator.tracker.anchors
    await p.at(50)
    assert p.flag() == 'off'
    await p.at(60, {s: 1100 for s in p.sources})
    assert p.flag() == 'on'
    for second in (70, 80, 90):
        await p.at(second, {s: 1100 + second for s in p.sources})
    recovered = [row for row in p.coordinator.intervals if row not in before]
    assert recovered
    assert all(datetime.fromisoformat(row['start']) >= START + timedelta(seconds=60) for row in recovered)
    assert p.coordinator.tracker.events['i']['measurement_validity_invalidated'] > 0


async def test_explicit_native_update_entity_is_a_cached_report_not_a_safe_integral_commit(native_path):
    """Counterexample/contract limit: external energy polling must be excluded.

    A real local HA update_entity call makes native integration publish its held
    counter before the pending flush. This is not a new physical/source commit.
    Do not use update_entity in the quality adapter or as measurement evidence.
    """
    p = native_path
    await p.at(10, {p.sources[0]: 1100})
    for seconds in (20, 30, 40, 50):
        await p.at(seconds)
    assert p.flag() == 'off'
    await p.at(60, {s: p.hass.states.get(s).state for s in p.sources})
    assert p.flag() == 'on' and not p.coordinator.tracker.anchors
    await p.at(61)
    before = p.counter()
    await p.hass.services.async_call('homeassistant', 'update_entity', {'entity_id': ENERGY}, blocking=True)
    await p.hass.async_block_till_done()
    stamp, value = p.coordinator.tracker.anchors['i']
    assert value == before and stamp == START + timedelta(seconds=61, milliseconds=500)
    for seconds in range(70, 311, 10):
        await p.at(seconds, {s: p.hass.states.get(s).state for s in p.sources})
    row, = p.coordinator.intervals
    duration = (datetime.fromisoformat(row['end']) - datetime.fromisoformat(row['start'])).total_seconds()
    watts = sum(float(p.hass.states.get(s).state) for s in p.sources)
    assert row['energy_kwh'] > watts * duration / 3600000
    assert row['energy_kwh'] - watts * duration / 3600000 == pytest.approx(watts * 51.5 / 3600000, abs=2e-9)
