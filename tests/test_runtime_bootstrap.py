"""Entry-only ML bootstrap boundaries, with native HA and synthetic failures.

No test downloads or installs a package. The successful native learner check
uses the development environment; platform/failure cases are synthetic, not
evidence of Musl delivery, source freshness, or forecast quality.
"""
import asyncio
import builtins
from importlib import metadata
import json
from pathlib import Path
import re
import sys
import textwrap
import threading
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

from homeassistant import requirements
from homeassistant.helpers import aiohttp_client, importlib as ha_importlib
from homeassistant.helpers.storage import Store
from packaging.requirements import Requirement
import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.adaptive_solar import _runtime as runtime, async_setup_entry


@pytest.fixture(autouse=True)
def forbid_package_install(monkeypatch):
    """A regression must fail rather than invoking a real package manager."""
    install = Mock(side_effect=AssertionError("runtime test attempted a real package install"))
    monkeypatch.setattr(requirements.pkg_util, "install_package", install)
    return install


def select_platform(monkeypatch, *, abi="cpython-314-x86_64-linux-gnu", machine="x86_64",
                    implementation="cpython", version=(3, 14), system="linux", free_threaded=0):
    """Change only the bootstrap's platform view, never the interpreter globals."""
    monkeypatch.setattr(runtime, "sys", SimpleNamespace(
        modules=sys.modules, implementation=SimpleNamespace(name=implementation),
        version_info=version, platform=system,
    ))
    monkeypatch.setattr(runtime, "platform", SimpleNamespace(machine=lambda: machine))
    values = {"SOABI": abi, "Py_GIL_DISABLED": free_threaded}
    monkeypatch.setattr(runtime, "sysconfig", SimpleNamespace(get_config_var=values.get))


def set_metadata(monkeypatch, value):
    def version(name):
        assert name == "scikit-learn"
        if isinstance(value, Exception):
            raise value
        return value

    monkeypatch.setattr(runtime, "metadata", SimpleNamespace(
        version=version, PackageNotFoundError=metadata.PackageNotFoundError,
    ))


async def run_isolated(code):
    """Cold imports must not inherit already imported native extension modules."""
    process = await asyncio.create_subprocess_exec(
        sys.executable, "-c", textwrap.dedent(code), cwd=Path(__file__).parents[1],
        stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
    )
    try:
        stdout, stderr = await asyncio.wait_for(process.communicate(), 60)
    except BaseException:
        if process.returncode is None:
            process.kill()
        await process.wait()
        raise
    assert process.returncode == 0, (stdout + stderr).decode()


def test_packaged_contract_is_exact_and_hash_pinned_without_freezing_release_hash():
    manifest = json.loads(Path(runtime.__file__).with_name("manifest.json").read_bytes())
    assert manifest["requirements"] == ["pvlib==0.16.1"]
    contract = runtime.runtime_contract()
    assert contract["requirements"] == ["scikit-learn==1.9.1"]
    requirement = Requirement(contract["musl_requirement"])
    assert requirement.name == "scikit-learn"
    assert re.fullmatch(
        r"https://github\.com/togo42/Adaptive-Solar/releases/download/"
        r"v[^/]+/scikit_learn-1\.9\.1\.tar\.gz#sha256=[0-9a-f]{64}", requirement.url,
    )


@pytest.mark.parametrize("payload", [
    None, [], True, {"schema": True}, {"schema": 1.0},
    {"schema": 2}, {"requirements": ["scikit-learn>=1.9.1"]},
    {"requirements": ["scikit-learn==1.9.1", "numpy"]},
    {"musl_requirement": None}, {"musl_requirement": []},
    {"musl_requirement": "scikit-learn@https://example.com/runtime.tar.gz#sha256=" + "a" * 64},
    {"musl_requirement": "scikit-learn@https://github.com/togo42/Adaptive-Solar/releases/"
                         "download/v1/scikit_learn-1.9.1.tar.gz"},
], ids=["null", "list", "bool", "bool-schema", "float-schema", "wrong-schema", "loose-pin",
        "extra-package", "null-url", "list-url", "foreign-url", "missing-hash"])
def test_malformed_contract_fails_closed(monkeypatch, tmp_path, payload):
    contract = runtime.runtime_contract()
    if isinstance(payload, dict):
        contract.update(payload)
        payload = contract
    (tmp_path / "runtime_requirements.json").write_text(json.dumps(payload))
    monkeypatch.setattr(runtime, "Path", lambda _: tmp_path / "_runtime.py")
    with pytest.raises(runtime.RuntimeDependencyError):
        runtime.runtime_contract()


@pytest.mark.parametrize("content", [None, b"{", b"\xff"])
def test_unreadable_contract_has_a_runtime_error(monkeypatch, tmp_path, content):
    if content is not None:
        (tmp_path / "runtime_requirements.json").write_bytes(content)
    monkeypatch.setattr(runtime, "Path", lambda _: tmp_path / "_runtime.py")
    with pytest.raises(runtime.RuntimeDependencyError) as raised:
        runtime.runtime_contract()
    assert isinstance(raised.value.__cause__, (OSError, ValueError))


@pytest.mark.parametrize("skip_pip", [False, True])
async def test_exact_installed_native_learner_needs_no_installer_even_offline(hass, monkeypatch, skip_pip):
    assert metadata.version("scikit-learn") == "1.9.1"
    hass.config.skip_pip = skip_pip
    hass.config.skip_pip_packages = ["scikit_learn"]
    native_probe = runtime.probe_runtime
    threads = []

    def probe():
        threads.append(threading.get_ident())
        assert threading.get_ident() != hass.loop_thread_id
        assert native_probe() is True
        from sklearn.ensemble import GradientBoostingRegressor

        learner = GradientBoostingRegressor(n_estimators=2, random_state=0)
        learner.fit([[0.0], [1.0], [2.0], [3.0]], [0.0, 1.0, 2.0, 3.0])
        assert len(learner.predict([[0.5], [2.5]])) == 2
        return True

    monkeypatch.setattr(runtime, "probe_runtime", probe)
    selector = Mock(side_effect=AssertionError("installed runtime must not select a delivery URL"))
    installer = AsyncMock(side_effect=AssertionError("installed runtime must work offline"))
    monkeypatch.setattr(runtime, "installation_requirement", selector)
    monkeypatch.setattr(requirements, "async_process_requirements", installer)
    await runtime.async_ensure_runtime(hass)
    assert threads and runtime.STATE_KEY in hass.data
    assert hass.data[runtime.STATE_KEY]["ready"] is True
    selector.assert_not_called()
    installer.assert_not_awaited()


@pytest.mark.parametrize("abi", ["cpython-314-x86_64-linux-musl", "cpython-314-x86_64-linux-gnu"])
async def test_missing_runtime_uses_native_requirements_and_worker_postcheck(hass, monkeypatch, abi):
    select_platform(monkeypatch, abi=abi)
    hass.config.skip_pip = False
    expected = runtime.runtime_contract()["musl_requirement"] if abi.endswith("musl") else "scikit-learn==1.9.1"
    installed = False
    events = []
    native_selector = runtime.installation_requirement
    native_process = requirements.async_process_requirements

    def probe():
        assert threading.get_ident() != hass.loop_thread_id
        events.append(("probe", installed))
        return installed

    def select():
        assert threading.get_ident() != hass.loop_thread_id
        events.append(("select",))
        return native_selector()

    def install_if_missing(selected, kwargs):
        nonlocal installed
        assert threading.get_ident() != hass.loop_thread_id
        assert selected == [expected]
        assert Path(kwargs["constraints"]).name == "package_constraints.txt"
        events.append(("install",))
        installed = True
        return {expected}, set()

    process = AsyncMock(wraps=native_process)
    monkeypatch.setattr(runtime, "probe_runtime", probe)
    monkeypatch.setattr(runtime, "installation_requirement", select)
    monkeypatch.setattr(requirements, "async_process_requirements", process)
    monkeypatch.setattr(requirements, "_install_requirements_if_missing", install_if_missing)
    await runtime.async_ensure_runtime(hass)
    process.assert_awaited_once_with(hass, "adaptive_solar", [expected], is_built_in=False)
    assert events == [("probe", False), ("select",), ("install",), ("probe", True)]
    assert hass.data[runtime.STATE_KEY]["ready"] is True
    assert expected in requirements._async_get_manager(hass).is_installed_cache


async def test_concurrent_entries_share_one_installation(hass, monkeypatch):
    select_platform(monkeypatch)
    hass.config.skip_pip = False
    entered, release = asyncio.Event(), asyncio.Event()
    installed = False

    async def install(*args, **kwargs):
        nonlocal installed
        entered.set()
        await release.wait()
        installed = True

    monkeypatch.setattr(runtime, "probe_runtime", lambda: installed)
    installer = AsyncMock(side_effect=install)
    monkeypatch.setattr(requirements, "async_process_requirements", installer)
    tasks = [asyncio.create_task(runtime.async_ensure_runtime(hass)) for _ in range(4)]
    try:
        await asyncio.wait_for(entered.wait(), 10)
        assert not any(task.done() for task in tasks)
        assert hass.data[runtime.STATE_KEY]["ready"] is False
    finally:
        release.set()
        await asyncio.gather(*tasks)
    installer.assert_awaited_once_with(hass, "adaptive_solar", ["scikit-learn==1.9.1"], is_built_in=False)
    assert hass.data[runtime.STATE_KEY]["ready"] is True


async def test_ready_runtime_disappearing_on_reload_never_reinstalls(hass, monkeypatch):
    monkeypatch.setattr(runtime, "probe_runtime", lambda: True)
    await runtime.async_ensure_runtime(hass)
    monkeypatch.setattr(runtime, "probe_runtime", lambda: False)
    installer = AsyncMock()
    monkeypatch.setattr(requirements, "async_process_requirements", installer)
    with pytest.raises(runtime.RuntimeDependencyError, match="disappeared"):
        await runtime.async_ensure_runtime(hass)
    installer.assert_not_awaited()


@pytest.mark.parametrize("version", ["1.8.0", "1.10.0", "1.9.1+local", "1.9.1.post1"])
async def test_wrong_metadata_version_is_not_repaired(hass, monkeypatch, version):
    set_metadata(monkeypatch, version)
    installer = AsyncMock()
    monkeypatch.setattr(requirements, "async_process_requirements", installer)
    with pytest.raises(runtime.RuntimeDependencyError, match="exactly"):
        await runtime.async_ensure_runtime(hass)
    installer.assert_not_awaited()
    assert hass.data[runtime.STATE_KEY]["ready"] is False


@pytest.mark.parametrize("failure", ["loaded-version", "missing-metadata", "missing-learner", "import-error", "abi-error"])
async def test_loaded_or_broken_runtime_is_not_repaired(hass, monkeypatch, failure):
    import sklearn
    from sklearn import ensemble

    set_metadata(monkeypatch, "1.9.1")
    if failure == "loaded-version":
        monkeypatch.setattr(sklearn, "__version__", "1.8.0")
    elif failure == "missing-metadata":
        set_metadata(monkeypatch, metadata.PackageNotFoundError("scikit-learn"))
    elif failure == "missing-learner":
        monkeypatch.setattr(ensemble, "GradientBoostingRegressor", None)
    else:
        original_import = builtins.__import__

        def fail_import(name, *args, **kwargs):
            if name == "sklearn.ensemble":
                if failure == "import-error":
                    raise ImportError("synthetic missing native learner")
                raise OSError("synthetic incompatible shared library")
            return original_import(name, *args, **kwargs)

        monkeypatch.setattr(builtins, "__import__", fail_import)
    installer = AsyncMock()
    monkeypatch.setattr(requirements, "async_process_requirements", installer)
    with pytest.raises(runtime.RuntimeDependencyError):
        await runtime.async_ensure_runtime(hass)
    installer.assert_not_awaited()
    assert hass.data[runtime.STATE_KEY]["ready"] is False


@pytest.mark.parametrize("skip_pip,packages", [
    (True, []), (False, ["scikit-learn"]), (False, ["scikit_learn"]), (False, ["Scikit.LeArN"]),
])
async def test_ha_installation_opt_out_is_respected_before_delivery_selection(hass, monkeypatch, skip_pip, packages):
    hass.config.skip_pip = skip_pip
    hass.config.skip_pip_packages = packages
    monkeypatch.setattr(runtime, "probe_runtime", lambda: False)
    selector = Mock(side_effect=AssertionError("disabled installation selected a source"))
    installer = AsyncMock()
    monkeypatch.setattr(runtime, "installation_requirement", selector)
    monkeypatch.setattr(requirements, "async_process_requirements", installer)
    with pytest.raises(runtime.RuntimeDependencyError, match="disabled"):
        await runtime.async_ensure_runtime(hass)
    selector.assert_not_called()
    installer.assert_not_awaited()


@pytest.mark.parametrize("platform_values", [
    {"abi": "cpython-314-x86_64-unknown"},
    {"abi": "cpython-314t-x86_64-linux-gnu"},
    {"free_threaded": 1}, {"machine": "aarch64"}, {"machine": "armv7l"},
    {"implementation": "pypy"}, {"version": (3, 13)}, {"system": "darwin"},
])
async def test_unqualified_platform_does_not_invoke_installer(hass, monkeypatch, platform_values):
    select_platform(monkeypatch, **platform_values)
    hass.config.skip_pip = False
    monkeypatch.setattr(runtime, "probe_runtime", lambda: False)
    installer = AsyncMock()
    monkeypatch.setattr(requirements, "async_process_requirements", installer)
    with pytest.raises(runtime.RuntimeDependencyError):
        await runtime.async_ensure_runtime(hass)
    installer.assert_not_awaited()


async def test_cancelled_installation_remains_blocked_even_if_runtime_later_appears(hass, monkeypatch):
    select_platform(monkeypatch)
    hass.config.skip_pip = False
    entered, release, finished = asyncio.Event(), threading.Event(), threading.Event()
    installed = False
    probes = []
    native_calls = []

    def probe():
        probes.append(installed)
        return installed

    def install(selected, kwargs):
        nonlocal installed
        try:
            assert threading.get_ident() != hass.loop_thread_id
            native_calls.append(selected)
            hass.loop.call_soon_threadsafe(entered.set)
            assert release.wait(10), "test did not release Core's installer worker"
            installed = True
            return set(selected), set()
        finally:
            finished.set()

    monkeypatch.setattr(runtime, "probe_runtime", probe)
    installer = AsyncMock(wraps=requirements.async_process_requirements)
    monkeypatch.setattr(requirements, "async_process_requirements", installer)
    # The HA plugin deliberately runs Mock executor targets on the loop;
    # keep this an ordinary function to exercise the real worker boundary.
    monkeypatch.setattr(requirements, "_install_requirements_if_missing", install)
    task = asyncio.create_task(runtime.async_ensure_runtime(hass))
    try:
        await asyncio.wait_for(entered.wait(), 10)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        state = hass.data[runtime.STATE_KEY]
        assert state["interrupted"] is True and state["ready"] is False
        # Cancellation does not stop the native package-manager thread.
        assert not finished.is_set()
        with pytest.raises(runtime.RuntimeDependencyError, match="interrupted"):
            await runtime.async_ensure_runtime(hass)
    finally:
        release.set()
        if not task.done():
            task.cancel()
        await asyncio.gather(task, return_exceptions=True)
        assert await hass.async_add_executor_job(finished.wait, 10)
    assert installed
    for _ in range(2):
        with pytest.raises(runtime.RuntimeDependencyError, match="interrupted"):
            await runtime.async_ensure_runtime(hass)
    assert installer.await_count == 1
    assert native_calls == [[runtime.ML_REQUIREMENT]]
    assert probes == [False]
    assert state["ready"] is False


async def test_native_failed_install_is_not_ready_and_core_does_not_retry(hass, monkeypatch):
    select_platform(monkeypatch)
    hass.config.skip_pip = False
    monkeypatch.setattr(runtime, "probe_runtime", lambda: False)
    low_level = Mock(return_value=(set(), {runtime.ML_REQUIREMENT}))
    monkeypatch.setattr(requirements, "_install_requirements_if_missing", low_level)
    for _ in range(2):
        with pytest.raises(requirements.RequirementsNotFound):
            await runtime.async_ensure_runtime(hass)
        assert hass.data[runtime.STATE_KEY]["ready"] is False
    low_level.assert_called_once()


@pytest.mark.parametrize("postcheck", [False, runtime.RuntimeDependencyError("synthetic native import failed")])
async def test_installer_return_without_usable_runtime_is_not_success(hass, monkeypatch, postcheck):
    select_platform(monkeypatch)
    hass.config.skip_pip = False
    results = iter([False, postcheck])

    def probe():
        result = next(results)
        if isinstance(result, Exception):
            raise result
        return result

    installer = AsyncMock()
    monkeypatch.setattr(runtime, "probe_runtime", probe)
    monkeypatch.setattr(requirements, "async_process_requirements", installer)
    with pytest.raises(runtime.RuntimeDependencyError):
        await runtime.async_ensure_runtime(hass)
    installer.assert_awaited_once()
    assert hass.data[runtime.STATE_KEY]["ready"] is False


async def test_entry_runtime_failure_precedes_weather_coordinator_and_store(hass, monkeypatch):
    from custom_components.adaptive_solar import coordinator, weather

    failure = runtime.RuntimeDependencyError("synthetic bootstrap failure")
    ensure = AsyncMock(side_effect=failure)
    monkeypatch.setattr(runtime, "async_ensure_runtime", ensure)
    native_import = ha_importlib.async_import_module
    imported = []

    async def import_module(hass, name):
        imported.append(name)
        return await native_import(hass, name)

    monkeypatch.setattr(ha_importlib, "async_import_module", import_module)
    construction = [
        (weather, "OpenMeteoClient"), (coordinator, "AdaptiveSolarCoordinator"),
        (aiohttp_client, "async_get_clientsession"), (Store, "__init__"),
    ]
    spies = []
    for module, name in construction:
        spy = Mock(side_effect=AssertionError(f"constructed {name} before bootstrap succeeded"))
        monkeypatch.setattr(module, name, spy)
        spies.append(spy)
    # Deliberately no site data: the gate must precede even config hydration.
    entry = MockConfigEntry(domain="adaptive_solar", data={})
    with pytest.raises(runtime.RuntimeDependencyError) as raised:
        await async_setup_entry(hass, entry)
    assert raised.value is failure
    ensure.assert_awaited_once_with(hass)
    assert imported == ["custom_components.adaptive_solar._runtime"]
    for spy in spies:
        spy.assert_not_called()


async def test_cold_bootstrap_and_offline_model_imports_need_neither_ha_nor_sklearn():
    await run_isolated('''
        import importlib.abc
        import sys

        class BlockRuntimeImports(importlib.abc.MetaPathFinder):
            def find_spec(self, fullname, path=None, target=None):
                if fullname.split(".")[0] in {"homeassistant", "sklearn"}:
                    raise AssertionError("offline import attempted " + fullname)
                return None

        sys.meta_path.insert(0, BlockRuntimeImports())
        from custom_components.adaptive_solar import _runtime
        from custom_components.adaptive_solar.core import archive, models
        assert _runtime.ML_REQUIREMENT == "scikit-learn==1.9.1"
        assert models.SiteConfig and archive.canonical_bytes({}) == b"{}"
        assert not {"homeassistant", "sklearn"}.intersection(sys.modules)
        from importlib import metadata
        from unittest.mock import patch
        with patch.object(_runtime.metadata, "version", side_effect=metadata.PackageNotFoundError):
            assert _runtime.probe_runtime() is False
    ''')


async def test_real_orphaned_sklearn_submodules_block_a_missing_metadata_install():
    await run_isolated('''
        import sklearn.ensemble
        import sys
        from importlib import metadata
        from unittest.mock import patch
        from custom_components.adaptive_solar import _runtime

        # Keep real loaded descendants but simulate a partially cleared root
        # only in this disposable interpreter, never in the pytest process.
        del sys.modules["sklearn"]
        assert "sklearn.ensemble" in sys.modules
        with patch.object(_runtime.metadata, "version", side_effect=metadata.PackageNotFoundError):
            try:
                _runtime.probe_runtime()
            except _runtime.RuntimeDependencyError as error:
                assert "restart required" in str(error)
            else:
                raise AssertionError("loaded descendants were treated as a fresh installation")
    ''')


async def test_cold_native_config_flow_import_does_not_bootstrap_ml():
    await run_isolated('''
        import importlib.abc
        import sys

        class BlockLearningImports(importlib.abc.MetaPathFinder):
            def find_spec(self, fullname, path=None, target=None):
                if fullname.split(".")[0] == "sklearn" or fullname.endswith("._runtime"):
                    raise AssertionError("config flow attempted " + fullname)
                return None

        sys.meta_path.insert(0, BlockLearningImports())
        from custom_components.adaptive_solar import config_flow
        from homeassistant import config_entries
        assert issubclass(config_flow.AdaptiveSolarConfigFlow, config_entries.ConfigFlow)
        assert "sklearn" not in sys.modules
        assert "custom_components.adaptive_solar._runtime" not in sys.modules
    ''')
