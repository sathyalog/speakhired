"""LEV running inside the app (LEV_MODE=local). The real model needs about 8 GB, so these tests use a stand-in `lev` package
that follows the same API: lev.load(checkpoint, cache_dir=...) -> engine; engine.system_one(state, questions) -> object with model_dump()."""
import os
import sys
import tempfile
import types
from pathlib import Path

os.environ.setdefault("DATA_DIR", tempfile.mkdtemp())

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from speakhired import main  # noqa: E402
from speakhired.agents import core  # noqa: E402
from speakhired.config import Settings  # noqa: E402
from speakhired.engines.delivery import delivery_metrics  # noqa: E402
from speakhired.llm import ModeStore  # noqa: E402
from speakhired.reasoning import lev as lev_module  # noqa: E402
from speakhired.reasoning.lev import LevClient, LevUnavailable  # noqa: E402
from speakhired.schemas import Question  # noqa: E402
from test_lev_contract import check_question  # noqa: E402

LOCAL = Settings(lev_mode="local", lev_checkpoint="interfaze-ai/lev")


class Response:
    def __init__(self, answers):
        self.answers = answers

    def model_dump(self):
        return {"model": "fake", "answers": self.answers, "usage": {"input_tokens": 1}}


class Engine:
    def __init__(self):
        self.calls = []

    def system_one(self, state, questions):
        self.calls.append((state, questions))
        for name, q in questions.items():
            check_question(name, q)          # the request must be valid for the real LEV too
        answers = {n: ({"type": "noul", "noul": 0.9} if q["type"] == "noul" else
                       {"type": "choice", "choice": "follow_up", "probabilities": {}, "confidence": 0.6} if q["type"] == "choice" else
                       {"type": "score", "score": 3.0, "probabilities": {}, "legend": {}, "confidence": 0.5}) for n, q in questions.items()}
        return Response(answers)


@pytest.fixture
def fake_lev(monkeypatch):
    loads = []
    module = types.ModuleType("lev")

    def load(checkpoint, cache_dir=None):
        loads.append((checkpoint, cache_dir))
        return Engine()
    module.load = load
    monkeypatch.setitem(sys.modules, "lev", module)
    monkeypatch.setattr(lev_module, "ram_gb", lambda: 32.0)
    return loads


def test_local_mode_reports_itself_as_this_computer():
    c = LevClient(LOCAL)
    assert c.enabled and c.in_process and not c.is_remote and c.location == "this_computer"


async def test_loads_once_in_the_background_thread_and_answers(fake_lev):
    c = LevClient(LOCAL)
    first = await c.decide("state", {"a": {"type": "noul", "instructions": "x"}})
    second = await c.decide("state", {"a": {"type": "noul", "instructions": "x"}})
    assert first == second == {"a": {"type": "noul", "noul": 0.9}}
    assert fake_lev == [("interfaze-ai/lev", None)]              # loaded a single time


async def test_cache_folder_setting_is_passed_to_lev(fake_lev):
    await LevClient(Settings(lev_mode="local", lev_cache_dir="/data/lev")).decide("s", {"a": {"type": "noul"}})
    assert fake_lev == [("interfaze-ai/lev", "/data/lev")]


async def test_small_computers_are_protected_from_loading_it(monkeypatch, fake_lev):
    monkeypatch.setattr(lev_module, "ram_gb", lambda: 8.0)
    c = LevClient(LOCAL)
    with pytest.raises(LevUnavailable) as e:
        await c.decide("s", {"a": {"type": "noul"}})
    assert "16 GB" in str(e.value) and "8 GB" in str(e.value) and "LEV_MODE=http" in str(e.value) and fake_lev == []
    health = await c.health()
    assert health["ok"] is False and health["status"] == "not loaded" and "16 GB" in health["error"]
    forced = LevClient(Settings(lev_mode="local", lev_local_force=True))
    assert await forced.decide("s", {"a": {"type": "noul"}}) and fake_lev          # the user can override


async def test_missing_package_gives_an_install_hint(monkeypatch):
    monkeypatch.setitem(sys.modules, "lev", None)           # makes `import lev` fail
    monkeypatch.setattr(lev_module, "ram_gb", lambda: 32.0)
    with pytest.raises(LevUnavailable) as e:
        await LevClient(LOCAL).decide("s", {"a": {"type": "noul"}})
    assert "uv sync --extra lev" in str(e.value)


async def test_load_failure_is_explained(monkeypatch):
    module = types.ModuleType("lev")
    module.load = lambda checkpoint, cache_dir=None: (_ for _ in ()).throw(MemoryError("out of memory"))
    monkeypatch.setitem(sys.modules, "lev", module)
    monkeypatch.setattr(lev_module, "ram_gb", lambda: 32.0)
    with pytest.raises(LevUnavailable) as e:
        await LevClient(LOCAL).decide("s", {"a": {"type": "noul"}})
    assert "could not be loaded" in str(e.value) and "MemoryError" in str(e.value)


async def test_health_goes_from_loading_to_ok(fake_lev):
    c = LevClient(LOCAL)
    assert (await c.health())["status"] == "loading"
    c.try_preload()                                             # what start-up does in the background
    assert (await c.health())["ok"] is True and (await c.health())["status"] == "ok"
    c2 = LevClient(Settings(lev_mode="local"))
    c2.try_preload(); c2.try_preload()
    assert len(fake_lev) == 2                                   # one load per client, not per call


async def test_interview_scoring_runs_through_local_lev(fake_lev):
    q = Question(id="1", text="What is a consumer group?", key_points=["partitions", "offsets"])
    ev = await core.evaluate(None, LevClient(LOCAL), q, "A consumer group shares partitions.", delivery_metrics("x", 1))
    assert ev.judge == "lev" and ev.covered_points == ["partitions", "offsets"]


@pytest.mark.parametrize("mode, lev_settings, mode_name, setup", [
    ("offline", Settings(lev_mode="off"), "offline", "fully_offline"),
    ("offline", Settings(lev_mode="local"), "offline", "fully_offline"),
    ("offline", Settings(lev_mode="http", lev_url="http://127.0.0.1:8000"), "offline", "fully_offline"),
    ("offline", Settings(lev_mode="http", lev_url="http://192.168.1.20:8000"), "offline", "offline_hosted_scoring"),
    ("offline", Settings(lev_mode="http", lev_url="https://me--lev.modal.run"), "offline", "offline_hosted_scoring"),
    ("online", Settings(lev_mode="local"), "online", "online"),
])
def test_the_three_setups_are_named(mode, lev_settings, mode_name, setup):
    main.mode_store = ModeStore(path=Path(tempfile.mkdtemp()) / "mode.json")
    main.mode_store.set(mode)
    main.lev = LevClient(lev_settings)
    info = TestClient(main.app).get("/api/mode").json()
    assert info["mode"] == mode_name and info["setup"] == setup
    assert info["lev"]["location"] == main.lev.location


async def test_health_keeps_lev_status_and_location_together(fake_lev):
    main.mode_store = ModeStore(path=Path(tempfile.mkdtemp()) / "mode.json")
    main.lev = LevClient(LOCAL)
    main.lev.try_preload()
    lev_info = TestClient(main.app).get("/api/health").json()["lev"]
    assert lev_info["ok"] is True and lev_info["status"] == "ok" and lev_info["location"] == "this_computer" and lev_info["mode"] == "local"
