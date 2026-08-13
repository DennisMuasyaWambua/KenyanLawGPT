"""Tests for GMI Cloud streaming + the streaming Ollama-fallback orchestrator.

Hermetic: ``requests.post`` is mocked to emit a fake OpenAI-compatible SSE
stream, so nothing touches the network. Covers incremental <think>-stripping
(including tags split across chunks), spend accounting from the final usage
chunk, up-front error surfacing, and the stream fallback chain.
"""
from unittest import mock

from django.test import TestCase, override_settings

from law_app.models import GmiSpend
from law_app.providers import gmi
from law_app.providers.gmi import (
    GMICloudError, GMICloudProvider, StreamChunk, _ThinkStreamFilter,
)
from law_app.providers.generation import generate_answer_stream, StreamResult


def _stream_resp(lines, status=200):
    """Fake streaming response whose iter_lines() replays SSE ``lines``."""
    m = mock.Mock()
    m.status_code = status
    m.iter_lines.return_value = list(lines)
    m.text = "" if status == 200 else "error body"
    m.close = mock.Mock()
    return m


def _sse(content_pieces, usage=None, reasoning_pieces=None):
    """Build SSE lines: reasoning deltas, then content deltas, usage, [DONE]."""
    import json
    lines = []
    for piece in (reasoning_pieces or []):
        lines.append("data: " + json.dumps(
            {"choices": [{"delta": {"reasoning": piece}}]}))
    for piece in content_pieces:
        lines.append("data: " + json.dumps(
            {"choices": [{"delta": {"content": piece}}]}))
    lines.append("data: " + json.dumps(
        {"choices": [], "usage": usage or
         {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15}}))
    lines.append("data: [DONE]")
    return lines


def _content(chunks):
    """Join the answer text from a StreamChunk iterator (ignoring reasoning)."""
    return "".join(c.text for c in chunks if c.kind == "content")


GMI_SETTINGS = dict(
    GMI_CLOUD_BASE_URL="https://api.gmi-serving.com/v1",
    GMI_CLOUD_API_KEY="test-key",
    GMI_CLOUD_DEEPSEEK_MODEL="deepseek-ai/DeepSeek-V4-Flash-0731",
    GMI_CLOUD_QWEN_MODEL="Qwen/Qwen3.7-Max",
    GMI_CLOUD_MODEL="Qwen/Qwen3.7-Max",
    GMI_CLOUD_DRAFT_MODEL="deepseek-ai/DeepSeek-V4-Flash-0731",
    GMI_CLOUD_RESEARCH_MODEL="Qwen/Qwen3.7-Max",
    GMI_CLOUD_TIMEOUT=30,
    GMI_CLOUD_ALLOW_REAL_DATA=False,
    GMI_CLOUD_DAILY_USD_CAP=10.0,
    GMI_CLOUD_MAX_OUTPUT_TOKENS=512,
    GMI_CLOUD_QWEN_PRICE_INPUT_PER_1M=1.0,
    GMI_CLOUD_QWEN_PRICE_OUTPUT_PER_1M=2.0,
    GMI_CLOUD_DEEPSEEK_PRICE_INPUT_PER_1M=0.0,
    GMI_CLOUD_DEEPSEEK_PRICE_OUTPUT_PER_1M=0.0,
)


class ThinkStreamFilterTests(TestCase):
    def test_strips_think_within_single_chunk(self):
        f = _ThinkStreamFilter()
        out = f.feed("<think>reasoning</think>Answer.") + f.flush()
        self.assertEqual(out, "Answer.")

    def test_strips_think_split_across_chunks(self):
        f = _ThinkStreamFilter()
        out = ""
        for chunk in ["Hello <thi", "nk>secret rea", "soning</thi", "nk> world"]:
            out += f.feed(chunk)
        out += f.flush()
        self.assertEqual(out, "Hello  world")

    def test_passes_through_when_no_think(self):
        f = _ThinkStreamFilter()
        out = f.feed("plain ") + f.feed("text") + f.flush()
        self.assertEqual(out, "plain text")


@override_settings(**GMI_SETTINGS)
class GMICloudStreamTests(TestCase):
    @mock.patch.object(gmi.requests, "post")
    def test_stream_yields_deltas_and_records_spend(self, post):
        post.return_value = _stream_resp(_sse(
            ["Hello", " ", "world"],
            usage={"prompt_tokens": 100, "completion_tokens": 40, "total_tokens": 140}))
        p = GMICloudProvider(model=GMI_SETTINGS["GMI_CLOUD_QWEN_MODEL"])
        pieces = list(p.generate_stream("q", contains_client_data=False))
        self.assertEqual(_content(pieces), "Hello world")
        # Qwen priced 1.0/2.0 per 1M: 100/1e6*1 + 40/1e6*2 = 0.00018
        self.assertAlmostEqual(GmiSpend.today_spend_usd(), 0.00018, places=8)
        # streaming was actually requested
        self.assertTrue(post.call_args.kwargs["json"]["stream"])

    @mock.patch.object(gmi.requests, "post")
    def test_stream_surfaces_reasoning_separately_from_content(self, post):
        post.return_value = _stream_resp(_sse(
            ["The answer."], reasoning_pieces=["Let me ", "think..."]))
        p = GMICloudProvider(model=GMI_SETTINGS["GMI_CLOUD_QWEN_MODEL"])
        pieces = list(p.generate_stream("q", contains_client_data=False))
        reasoning = "".join(c.text for c in pieces if c.kind == "reasoning")
        self.assertEqual(reasoning, "Let me think...")
        self.assertEqual(_content(pieces), "The answer.")
        # reasoning never leaks into the answer
        self.assertNotIn("think", _content(pieces))

    @mock.patch.object(gmi.requests, "post")
    def test_stream_strips_think_for_cot_model(self, post):
        post.return_value = _stream_resp(_sse(["<think>cot", " here</think>", "Final."]))
        p = GMICloudProvider(model="deepseek-ai/DeepSeek-R1-Distill-Llama-70B")
        self.assertTrue(p.strip_think)
        pieces = list(p.generate_stream("q", contains_client_data=False))
        self.assertEqual(_content(pieces), "Final.")

    @mock.patch.object(gmi.requests, "post")
    def test_stream_keeps_think_for_instruct_model(self, post):
        post.return_value = _stream_resp(_sse(["<think>keep</think>", "Answer."]))
        p = GMICloudProvider(model=GMI_SETTINGS["GMI_CLOUD_QWEN_MODEL"])
        self.assertFalse(p.strip_think)
        pieces = list(p.generate_stream("q", contains_client_data=False))
        self.assertIn("<think>keep</think>", _content(pieces))

    @mock.patch.object(gmi.requests, "post")
    def test_stream_http_error_raises_before_first_yield(self, post):
        post.return_value = _stream_resp([], status=500)
        gen = GMICloudProvider().generate_stream("q", contains_client_data=False)
        with self.assertRaises(GMICloudError):
            next(gen)


@override_settings(**GMI_SETTINGS)
class GenerationStreamFallbackTests(TestCase):
    @mock.patch.object(gmi.requests, "post")
    def test_stream_served_by_gmi_on_success(self, post):
        post.return_value = _stream_resp(_sse(["a", "b"]))
        res = generate_answer_stream(
            "q", contains_client_data=False,
            ollama_stream_fallback=lambda: iter(["ollama"]))
        self.assertIsInstance(res, StreamResult)
        self.assertTrue(res.served_by.startswith("gmi:"))
        self.assertEqual(_content(res.chunks), "ab")

    @mock.patch.object(gmi.requests, "post")
    def test_stream_falls_back_to_ollama_on_network_error(self, post):
        post.side_effect = gmi.requests.RequestException("down")
        res = generate_answer_stream(
            "q", contains_client_data=False,
            ollama_stream_fallback=lambda: iter(["ollama ", "answer"]))
        self.assertEqual(res.served_by, "ollama")
        self.assertIn("gmi-error", res.fallback_reason)
        self.assertEqual(_content(res.chunks), "ollama answer")

    @mock.patch.object(gmi.requests, "post")
    def test_stream_falls_back_on_http_error_before_first_token(self, post):
        post.return_value = _stream_resp([], status=500)
        res = generate_answer_stream(
            "q", contains_client_data=False,
            ollama_stream_fallback=lambda: iter(["ollama"]))
        self.assertEqual(res.served_by, "ollama")
        self.assertEqual(_content(res.chunks), "ollama")

    def test_stream_falls_back_when_not_configured(self):
        with override_settings(GMI_CLOUD_API_KEY=""):
            res = generate_answer_stream(
                "q", contains_client_data=False,
                ollama_stream_fallback=lambda: iter(["ollama"]))
            self.assertEqual(res.served_by, "ollama")
            self.assertEqual(res.fallback_reason, "gmi-not-configured")
