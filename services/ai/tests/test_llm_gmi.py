"""GMICloudProvider: model selection, conditional <think> stripping,
per-request usage capture, and the non-prod synthetic-data gate."""
import types

import pytest

from app.config import Config
from app.llm import GMICloudProvider


def _cfg(**over) -> Config:
    cfg = Config()
    cfg.gmi_cloud_base_url = "https://gmi.test/v1"
    cfg.gmi_cloud_api_key = "test-key"
    cfg.gmi_cloud_model = "deepseek-ai/DeepSeek-R1-Distill-Llama-70B"
    cfg.gmi_cloud_deepseek_model = "deepseek-ai/DeepSeek-R1-Distill-Llama-70B"
    cfg.gmi_cloud_qwen_model = "Qwen/Qwen3-235B-A22B-Instruct-2507-FP8"
    cfg.env = "dev"
    cfg.gmi_synthetic_only = True
    cfg.gmi_synthetic_data_ok = True  # gate opened by default in most tests
    for k, v in over.items():
        setattr(cfg, k, v)
    return cfg


class _FakeResp:
    def __init__(self, payload):
        self._payload = payload

    def raise_for_status(self):
        return None

    def json(self):
        return self._payload


class _FakeClient:
    """Stand-in for httpx.AsyncClient that records the request and returns a
    canned chat-completions payload."""

    def __init__(self, payload, sink):
        self._payload = payload
        self._sink = sink

    def __init_subclass__(cls):  # pragma: no cover
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    async def post(self, url, json=None, headers=None):
        self._sink["url"] = url
        self._sink["json"] = json
        self._sink["headers"] = headers
        return _FakeResp(self._payload)


def _fake_httpx(payload, sink):
    mod = types.SimpleNamespace()
    mod.AsyncClient = lambda *a, **k: _FakeClient(payload, sink)
    return mod


def _payload(content, usage=None):
    return {
        "choices": [{"message": {"content": content}}],
        "usage": usage or {"prompt_tokens": 11, "completion_tokens": 22, "total_tokens": 33},
    }


def test_model_param_overrides_default():
    cfg = _cfg()
    assert GMICloudProvider(cfg)._model == cfg.gmi_cloud_model
    p = GMICloudProvider(cfg, model=cfg.gmi_cloud_qwen_model)
    assert p._model == cfg.gmi_cloud_qwen_model
    assert p._reasoning is False  # Qwen3 is not a chain-of-thought model
    assert GMICloudProvider(cfg, model=cfg.gmi_cloud_deepseek_model)._reasoning is True


@pytest.mark.asyncio
async def test_deepseek_strips_think_block():
    cfg = _cfg()
    sink = {}
    p = GMICloudProvider(cfg, model=cfg.gmi_cloud_deepseek_model)
    p._httpx = _fake_httpx(_payload("<think>weighing options</think>The Act says X."), sink)
    out = await p.complete(system="s", prompt="q")
    assert out == "The Act says X."
    assert sink["json"]["model"] == cfg.gmi_cloud_deepseek_model
    assert sink["headers"]["Authorization"] == "Bearer test-key"


@pytest.mark.asyncio
async def test_qwen_does_not_strip_think_block():
    cfg = _cfg()
    p = GMICloudProvider(cfg, model=cfg.gmi_cloud_qwen_model)
    # Even if the text contained think-like tags, Qwen output must pass through.
    p._httpx = _fake_httpx(_payload("<think>should stay</think>final"), {})
    out = await p.complete(system="s", prompt="q")
    assert out == "<think>should stay</think>final"


@pytest.mark.asyncio
async def test_usage_and_latency_captured():
    cfg = _cfg()
    p = GMICloudProvider(cfg, model=cfg.gmi_cloud_qwen_model)
    p._httpx = _fake_httpx(_payload("ok", {"prompt_tokens": 5, "completion_tokens": 7, "total_tokens": 12}), {})
    await p.complete(system="s", prompt="q")
    assert p.last_usage == {"prompt_tokens": 5, "completion_tokens": 7, "total_tokens": 12}
    assert p.last_latency_ms >= 0


@pytest.mark.asyncio
async def test_synthetic_gate_blocks_non_prod_without_attestation():
    cfg = _cfg(gmi_synthetic_data_ok=False)  # gate closed, non-prod
    p = GMICloudProvider(cfg, model=cfg.gmi_cloud_qwen_model)
    p._httpx = _fake_httpx(_payload("nope"), {})
    with pytest.raises(RuntimeError, match="synthetic-data-only gate"):
        await p.complete(system="s", prompt="q")


@pytest.mark.asyncio
async def test_synthetic_gate_allows_prod():
    cfg = _cfg(env="prod", gmi_synthetic_data_ok=False)
    p = GMICloudProvider(cfg, model=cfg.gmi_cloud_qwen_model)
    p._httpx = _fake_httpx(_payload("prod answer"), {})
    assert await p.complete(system="s", prompt="q") == "prod answer"
