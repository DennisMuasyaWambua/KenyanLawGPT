"""FallbackProvider circuit breaker: a failing primary is skipped for a cooldown
instead of costing its full timeout on every request."""
import pytest

from app.llm import FallbackProvider


class _Flaky:
    def __init__(self, fail):
        self.fail, self.calls = fail, 0

    async def complete(self, system, prompt, max_tokens=2048, fast=False):
        self.calls += 1
        if self.fail:
            raise RuntimeError("504 Gateway Timeout")
        return "primary"

    async def stream(self, system, prompt, max_tokens=8192):
        self.calls += 1
        if self.fail:
            raise RuntimeError("504 Gateway Timeout")
        yield "primary"


class _Ok:
    async def complete(self, system, prompt, max_tokens=2048, fast=False):
        return "fallback"

    async def stream(self, system, prompt, max_tokens=8192):
        yield "fallback"


@pytest.mark.asyncio
async def test_failed_primary_is_skipped_during_cooldown(monkeypatch):
    now = [1000.0]
    monkeypatch.setattr("app.llm.time.monotonic", lambda: now[0])
    primary = _Flaky(fail=True)
    fb = FallbackProvider(primary, _Ok(), "gmi", "ollama", cooldown_seconds=300)

    assert await fb.complete("s", "p") == "fallback"
    assert primary.calls == 1
    # Within the cooldown: straight to the fallback, primary not retried.
    assert await fb.complete("s", "p", fast=True) == "fallback"
    assert [t async for t in fb.stream("s", "p")] == ["fallback"]
    assert primary.calls == 1
    # After the cooldown the primary is probed again (and recovers here).
    now[0] += 301
    primary.fail = False
    assert await fb.complete("s", "p") == "primary"
    assert primary.calls == 2


@pytest.mark.asyncio
async def test_stream_failure_before_first_token_trips_breaker(monkeypatch):
    monkeypatch.setattr("app.llm.time.monotonic", lambda: 50.0)
    primary = _Flaky(fail=True)
    fb = FallbackProvider(primary, _Ok(), cooldown_seconds=60)
    assert [t async for t in fb.stream("s", "p")] == ["fallback"]
    assert await fb.complete("s", "p") == "fallback"
    assert primary.calls == 1
