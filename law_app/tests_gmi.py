"""Tests for the GMI Cloud provider, cost/data gates and Ollama fallback.

Hermetic: ``requests.post`` inside the provider is mocked, so nothing touches
the network. Covers model selection, conditional <think>-stripping, token/cost
accounting, the data-sensitivity and daily-budget gates, and the fallback chain.
"""
from unittest import mock

from django.test import TestCase, override_settings

from law_app.models import GmiSpend
from law_app.providers import gmi
from law_app.providers.gmi import (
    GMICloudBudgetExceeded, GMICloudDisabled, GMICloudError, GMICloudProvider,
)
from law_app.providers.generation import generate_answer


def _resp(content, usage=None, status=200):
    m = mock.Mock()
    m.status_code = status
    m.json.return_value = {
        "choices": [{"message": {"content": content}}],
        "usage": usage or {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15},
    }
    m.text = content
    return m


GMI_SETTINGS = dict(
    GMI_CLOUD_BASE_URL="https://api.gmi-serving.com/v1",
    GMI_CLOUD_API_KEY="test-key",
    GMI_CLOUD_DEEPSEEK_MODEL="deepseek-ai/DeepSeek-R1-Distill-Llama-70B",
    GMI_CLOUD_QWEN_MODEL="Qwen/Qwen3-235B-A22B-Instruct-2507-FP8",
    GMI_CLOUD_MODEL="deepseek-ai/DeepSeek-R1-Distill-Llama-70B",
    GMI_CLOUD_TIMEOUT=30,
    GMI_CLOUD_ALLOW_REAL_DATA=False,
    GMI_CLOUD_DAILY_USD_CAP=10.0,
    GMI_CLOUD_MAX_OUTPUT_TOKENS=512,
    GMI_CLOUD_QWEN_PRICE_INPUT_PER_1M=1.0,
    GMI_CLOUD_QWEN_PRICE_OUTPUT_PER_1M=2.0,
    GMI_CLOUD_DEEPSEEK_PRICE_INPUT_PER_1M=0.0,
    GMI_CLOUD_DEEPSEEK_PRICE_OUTPUT_PER_1M=0.0,
)


@override_settings(**GMI_SETTINGS)
class GMICloudProviderTests(TestCase):
    def test_model_defaults_to_setting_and_can_be_overridden(self):
        self.assertEqual(GMICloudProvider().model, GMI_SETTINGS["GMI_CLOUD_MODEL"])
        self.assertEqual(GMICloudProvider(model="foo/bar").model, "foo/bar")

    @mock.patch.object(gmi.requests, "post")
    def test_think_stripped_for_deepseek_cot_model(self, post):
        post.return_value = _resp("<think>chain of thought</think>Final answer.")
        p = GMICloudProvider(model=GMI_SETTINGS["GMI_CLOUD_DEEPSEEK_MODEL"])
        self.assertTrue(p.strip_think)
        res = p.generate("q", contains_client_data=False)
        self.assertEqual(res.text, "Final answer.")
        self.assertIn("<think>", res.raw_text)  # raw preserved

    @mock.patch.object(gmi.requests, "post")
    def test_think_not_stripped_for_qwen_instruct_model(self, post):
        post.return_value = _resp("<think>keep me</think>Answer.")
        p = GMICloudProvider(model=GMI_SETTINGS["GMI_CLOUD_QWEN_MODEL"])
        self.assertFalse(p.strip_think)
        res = p.generate("q", contains_client_data=False)
        self.assertIn("<think>keep me</think>", res.text)

    @mock.patch.object(gmi.requests, "post")
    def test_token_usage_and_cost_recorded(self, post):
        post.return_value = _resp(
            "ok", usage={"prompt_tokens": 100, "completion_tokens": 40, "total_tokens": 140})
        p = GMICloudProvider(model=GMI_SETTINGS["GMI_CLOUD_QWEN_MODEL"])
        res = p.generate("q", contains_client_data=False)
        self.assertEqual((res.prompt_tokens, res.completion_tokens), (100, 40))
        # Qwen priced 1.0/2.0 per 1M: 100/1e6*1 + 40/1e6*2 = 0.00018
        self.assertAlmostEqual(res.cost_usd, 0.00018, places=8)
        self.assertAlmostEqual(GmiSpend.today_spend_usd(), 0.00018, places=8)

    @mock.patch.object(gmi.requests, "post")
    def test_sends_model_and_max_tokens(self, post):
        post.return_value = _resp("ok")
        GMICloudProvider(model="foo/bar").generate("q", contains_client_data=False)
        body = post.call_args.kwargs["json"]
        self.assertEqual(body["model"], "foo/bar")
        self.assertEqual(body["max_tokens"], GMI_SETTINGS["GMI_CLOUD_MAX_OUTPUT_TOKENS"])

    @mock.patch.object(gmi.requests, "post")
    def test_real_data_blocked_when_flag_false(self, post):
        with self.assertRaises(GMICloudDisabled):
            GMICloudProvider().generate("client secret", contains_client_data=True)
        post.assert_not_called()

    @override_settings(GMI_CLOUD_ALLOW_REAL_DATA=True)
    @mock.patch.object(gmi.requests, "post")
    def test_real_data_allowed_when_flag_true(self, post):
        post.return_value = _resp("ok")
        res = GMICloudProvider().generate("client secret", contains_client_data=True)
        self.assertEqual(res.text, "ok")

    @mock.patch.object(gmi.requests, "post")
    def test_synthetic_data_always_allowed(self, post):
        post.return_value = _resp("ok")
        res = GMICloudProvider().generate("public statute", contains_client_data=False)
        self.assertEqual(res.text, "ok")

    @mock.patch.object(gmi.requests, "post")
    def test_daily_budget_cap_blocks(self, post):
        GmiSpend.record(0, 0, 10.0)  # hit the $10 cap
        with self.assertRaises(GMICloudBudgetExceeded):
            GMICloudProvider(model=GMI_SETTINGS["GMI_CLOUD_QWEN_MODEL"]).generate(
                "q", contains_client_data=False)
        post.assert_not_called()

    @mock.patch.object(gmi.requests, "post")
    def test_http_error_raises_gmi_error(self, post):
        post.return_value = _resp("boom", status=500)
        with self.assertRaises(GMICloudError):
            GMICloudProvider().generate("q", contains_client_data=False)


@override_settings(**GMI_SETTINGS)
class GenerationFallbackTests(TestCase):
    @mock.patch.object(gmi.requests, "post")
    def test_served_by_gmi_on_success(self, post):
        post.return_value = _resp("gmi answer")
        res = generate_answer("q", contains_client_data=False,
                              ollama_fallback=lambda: "ollama answer")
        self.assertEqual(res.text, "gmi answer")
        self.assertTrue(res.served_by.startswith("gmi:"))

    @mock.patch.object(gmi.requests, "post")
    def test_falls_back_to_ollama_on_gmi_network_error(self, post):
        post.side_effect = gmi.requests.RequestException("down")
        res = generate_answer("q", contains_client_data=False,
                              ollama_fallback=lambda: "ollama answer")
        self.assertEqual(res.text, "ollama answer")
        self.assertEqual(res.served_by, "ollama")
        self.assertIn("gmi-error", res.fallback_reason)

    def test_falls_back_when_gmi_not_configured(self):
        with override_settings(GMI_CLOUD_API_KEY=""):
            res = generate_answer("q", contains_client_data=False,
                                  ollama_fallback=lambda: "ollama answer")
            self.assertEqual(res.served_by, "ollama")
            self.assertEqual(res.fallback_reason, "gmi-not-configured")

    @mock.patch.object(gmi.requests, "post")
    def test_budget_exceeded_falls_back_not_errors(self, post):
        GmiSpend.record(0, 0, 10.0)
        res = generate_answer("q", model=GMI_SETTINGS["GMI_CLOUD_QWEN_MODEL"],
                              contains_client_data=False,
                              ollama_fallback=lambda: "ollama answer")
        self.assertEqual(res.served_by, "ollama")
        self.assertIn("gmi-disabled", res.fallback_reason)
        post.assert_not_called()
