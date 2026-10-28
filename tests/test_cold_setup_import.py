"""Exercise actual setup from an uncached interpreter with native HA imports."""
import asyncio
from pathlib import Path
import sys
import textwrap


async def test_cold_setup_imports_physics_dependencies_outside_event_loop():
    code = textwrap.dedent('''
        import asyncio
        import importlib.abc
        import sys
        import threading
        from types import SimpleNamespace
        from unittest.mock import patch

        from custom_components.adaptive_solar import async_setup_entry
        from homeassistant.helpers import aiohttp_client

        watched = {"pvlib", "numpy", "scipy", "sklearn"}
        assert not watched.intersection(sys.modules)
        seen = set()
        loop_thread = threading.get_ident()

        class VerifyThread(importlib.abc.MetaPathFinder):
            def find_spec(self, fullname, path=None, target=None):
                if fullname.split(".")[0] in watched:
                    assert threading.get_ident() != loop_thread, fullname
                    seen.add(fullname.split(".")[0])
                return None

        class StopAfterImports(Exception):
            pass

        def session(_hass):
            raise StopAfterImports

        async def run():
            class Hass:
                data = {}
                loop = asyncio.get_running_loop()

                async def async_add_import_executor_job(self, target, *args):
                    return await asyncio.to_thread(target, *args)

            entry = SimpleNamespace(options={}, data={"site": {
                "latitude": 52, "longitude": 13, "timezone": "UTC",
                "strings": [{"id": "s", "inverter_id": "i", "peak_kw": 5,
                             "tilt_deg": 30, "azimuth_deg": 180}],
                "inverters": [{"id": "i", "max_ac_kw": 5}],
            }})
            with patch.object(aiohttp_client, "async_get_clientsession", session):
                try:
                    await async_setup_entry(Hass(), entry)
                except StopAfterImports:
                    pass
                else:
                    raise AssertionError("setup did not reach the session boundary")

        sys.meta_path.insert(0, VerifyThread())
        asyncio.run(run())
        assert {"pvlib", "numpy", "scipy"} <= seen, seen
    ''')
    process = await asyncio.create_subprocess_exec(
        sys.executable, "-c", code, cwd=Path(__file__).parents[1],
        stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
    )
    stdout, stderr = await asyncio.wait_for(process.communicate(), 60)
    assert process.returncode == 0, (stdout + stderr).decode()
