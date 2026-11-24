"""'auto' LLM selection: GMI Cloud is picked once its key is set and its
synthetic-data gate allows real calls (always in prod)."""
from app.config import Config
from app import llm


def _cfg(**kw):
    cfg = Config()
    cfg.llm_provider, cfg.anthropic_api_key, cfg.gmi_cloud_api_key = "auto", "", ""
    cfg.env, cfg.gmi_synthetic_only, cfg.gmi_synthetic_data_ok = "dev", True, False
    for k, v in kw.items():
        setattr(cfg, k, v)
    return cfg


def test_auto_picks_gmi_in_prod_when_keyed(monkeypatch):
    monkeypatch.setattr(llm, "_ollama_reachable", lambda cfg: False)
    assert isinstance(llm._make_primary(_cfg(env="prod", gmi_cloud_api_key="k")), llm.GMICloudProvider)


def test_auto_skips_gmi_when_gated_or_unkeyed(monkeypatch):
    monkeypatch.setattr(llm, "_ollama_reachable", lambda cfg: False)
    # Non-prod with the synthetic-only gate closed: a GMI call would be refused.
    assert isinstance(llm._make_primary(_cfg(gmi_cloud_api_key="k")), llm.MockProvider)
    assert isinstance(llm._make_primary(_cfg(env="prod")), llm.MockProvider)
    assert isinstance(llm._make_primary(_cfg(gmi_cloud_api_key="k", gmi_synthetic_data_ok=True)),
                      llm.GMICloudProvider)


def test_anthropic_key_still_wins(monkeypatch):
    monkeypatch.setattr(llm, "_ollama_reachable", lambda cfg: False)
    cfg = _cfg(env="prod", gmi_cloud_api_key="k", anthropic_api_key="a")
    assert isinstance(llm._make_primary(cfg), llm.AnthropicProvider)
