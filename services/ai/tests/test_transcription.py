"""Transcription provider selection, audio detection, and the KDPA-safe rule
that cloud STT is never auto-selected."""
import pytest

from app.config import Config
from app.transcription import (
    MockTranscriptionProvider,
    is_audio,
    make_transcriber,
)


@pytest.mark.parametrize("filename,mime,expected", [
    ("call.mp3", "", True),
    ("meeting.wav", "audio/wav", True),
    ("note.m4a", "", True),
    ("clip.webm", "video/webm", True),
    ("contract.pdf", "application/pdf", False),
    ("brief.docx", "", False),
    ("recording", "audio/ogg", True),
])
def test_is_audio(filename, mime, expected):
    assert is_audio(filename, mime) is expected


@pytest.mark.asyncio
async def test_mock_transcriber_is_watermarked_and_nonempty():
    result = await MockTranscriptionProvider().transcribe(b"\x00\x01\x02", "call.mp3", "audio/mpeg")
    assert result.text.strip()
    assert "mock transcript" in result.text.lower()
    assert result.provider == "mock"


def test_auto_never_selects_cloud(monkeypatch):
    # With no local Whisper installed, auto must fall back to the offline mock,
    # never the cloud provider — audio must not leave the box implicitly.
    monkeypatch.setattr("app.transcription._faster_whisper_available", lambda: False)
    cfg = Config()
    cfg.transcribe_provider = "auto"
    assert isinstance(make_transcriber(cfg), MockTranscriptionProvider)


def test_explicit_mock_selection():
    cfg = Config()
    cfg.transcribe_provider = "mock"
    assert isinstance(make_transcriber(cfg), MockTranscriptionProvider)


@pytest.mark.asyncio
async def test_lazy_transcriber_builds_once_and_retries_failed_builds(monkeypatch):
    import asyncio

    from app.transcription import LazyTranscriber

    calls = {"n": 0}

    def flaky_factory(cfg):
        calls["n"] += 1
        if calls["n"] == 1:
            raise RuntimeError("model download failed")
        return MockTranscriptionProvider()

    monkeypatch.setattr("app.transcription.make_transcriber", flaky_factory)
    lazy = LazyTranscriber(Config())
    with pytest.raises(RuntimeError):
        await lazy.transcribe(b"x", "a.wav")
    # Failure isn't cached; concurrent callers then share a single build.
    results = await asyncio.gather(*(lazy.transcribe(b"x", "a.wav") for _ in range(5)))
    assert all(r.provider == "mock" for r in results)
    assert calls["n"] == 2


def test_whisper_never_disables_vad(monkeypatch):
    """Regression: running Whisper with vad_filter=False on silent audio makes it
    hallucinate and grind for minutes. The empty-result retry must only make the
    VAD more sensitive."""
    import sys
    import types

    calls = []

    class FakeModel:
        def __init__(self, *a, **kw):
            pass

        def transcribe(self, path, **kw):
            calls.append(kw)
            return iter(()), types.SimpleNamespace(language="en")

        def detect_language(self, samples, **kw):
            return "yo", 0.6, [("yo", 0.6), ("sw", 0.3), ("en", 0.1)]

    monkeypatch.setitem(sys.modules, "faster_whisper", types.SimpleNamespace(WhisperModel=FakeModel))
    monkeypatch.setitem(sys.modules, "faster_whisper.audio",
                        types.SimpleNamespace(decode_audio=lambda *a, **k: [0.0] * 16000))
    from app.transcription import FasterWhisperProvider

    result = FasterWhisperProvider(Config())._run(b"\x00" * 10, "silence.webm")
    assert result.text == ""
    assert len(calls) == 2
    assert all(kw["vad_filter"] is True for kw in calls)
    assert all(kw["condition_on_previous_text"] is False for kw in calls)
    assert calls[1]["vad_parameters"]["threshold"] < 0.5
    # Detection is restricted to the allowed languages: "yo" wins overall, but
    # the best allowed language (sw) is what gets used.
    assert all(kw["language"] == "sw" for kw in calls)


def test_pinned_language_skips_detection(monkeypatch):
    import types

    from app.transcription import FasterWhisperProvider

    p = FasterWhisperProvider.__new__(FasterWhisperProvider)
    cfg = Config()
    cfg.transcribe_language = "sw"
    p._cfg = cfg
    p._model = types.SimpleNamespace(detect_language=lambda *a, **k: (_ for _ in ()).throw(AssertionError("called")))
    assert p._pick_language(None) == "sw"
    cfg.transcribe_language, cfg.transcribe_languages = "auto", ["en"]
    assert p._pick_language(None) == "en"


def test_diarize_requests_word_timings_and_labels_speakers(monkeypatch):
    import sys
    import types

    from app.diarization import Turn

    calls = []
    W = types.SimpleNamespace

    class FakeModel:
        def __init__(self, *a, **kw):
            pass

        def transcribe(self, samples, **kw):
            calls.append(kw)
            seg = W(text=" Habari. Karibu.", words=[W(start=0.1, end=0.6, word=" Habari."),
                                                    W(start=1.6, end=2.0, word=" Karibu.")])
            return iter([seg]), W(language="sw")

    class FakeDiarizer:
        def diarize(self, samples, num_speakers=0):
            assert num_speakers == 2
            return [Turn(0.0, 1.0, 5), Turn(1.5, 2.5, 9)]

    monkeypatch.setitem(sys.modules, "faster_whisper", types.SimpleNamespace(WhisperModel=FakeModel))
    monkeypatch.setitem(sys.modules, "faster_whisper.audio",
                        types.SimpleNamespace(decode_audio=lambda *a, **k: [0.0] * 16000))
    from app.transcription import FasterWhisperProvider

    cfg = Config()
    cfg.transcribe_language = "sw"
    p = FasterWhisperProvider(cfg)
    p._diarizer, p._diarizer_built = FakeDiarizer(), True
    result = p._run(b"x", "m.webm", diarize=True, num_speakers=2)
    assert calls[0]["word_timestamps"] is True
    assert result.text == "Habari. Karibu."
    assert [(u["speaker"], u["text"]) for u in result.segments] == [(1, "Habari."), (2, "Karibu.")]

    # Archive ingestion (no diarize) keeps the cheaper path and no speakers.
    calls.clear()
    assert p._run(b"x", "m.webm").segments == []
    assert "word_timestamps" not in calls[0]


def test_failed_diarization_keeps_the_transcript(monkeypatch):
    import types

    from app.transcription import FasterWhisperProvider

    p = FasterWhisperProvider.__new__(FasterWhisperProvider)
    p._cfg = Config()

    class Broken:
        def diarize(self, *a, **k):
            raise RuntimeError("onnx exploded")

    p._diarizer, p._diarizer_built = Broken(), True
    seg = types.SimpleNamespace(words=[types.SimpleNamespace(start=0, end=1, word=" hi")])
    assert p._speakers([0.0], [seg], 0) == []


def test_single_speaker_skips_the_diarizer():
    import types

    from app.transcription import FasterWhisperProvider

    p = FasterWhisperProvider.__new__(FasterWhisperProvider)
    p._cfg = Config()

    class MustNotRun:
        def diarize(self, *a, **k):
            raise AssertionError("diarizer called for a one-person recording")

    p._diarizer, p._diarizer_built = MustNotRun(), True
    W = types.SimpleNamespace
    segs = [W(words=[W(start=0.0, end=0.5, word=" Dictating"), W(start=0.6, end=1.0, word=" notes.")]),
            W(words=[W(start=9.0, end=9.5, word=" End.")])]
    assert p._speakers([0.0], segs, 1) == [
        {"speaker": 1, "start": 0.0, "end": 9.5, "text": "Dictating notes. End."}]


def test_recording_hotwords_come_before_the_configured_vocabulary():
    from app.transcription import _join_hotwords

    assert _join_hotwords("Grace Wanjiru, Milimani", " ELRC ") == "Grace Wanjiru, Milimani, ELRC"
    assert _join_hotwords("", "") == ""


def test_allowed_languages_restricts_every_detection():
    """Per-window detection (faster-whisper's multilingual mode) takes the top
    language from the CTranslate2 model; the wrapper must never let an
    unrelated language win, and must keep Whisper's ranking among the rest."""
    import types

    from app.transcription import _AllowedLanguages

    inner = types.SimpleNamespace(
        detect_language=lambda enc: [[("<|yo|>", 0.5), ("<|sw|>", 0.3), ("<|en|>", 0.2)],
                                     [("<|en|>", 0.7), ("<|sw|>", 0.1), ("<|so|>", 0.05)]],
        is_multilingual=True)
    wrapped = _AllowedLanguages(inner, ["en", "sw"])
    seen = wrapped.track()
    out = wrapped.detect_language("encoder-output")
    assert [r[0][0] for r in out] == ["<|sw|>", "<|en|>"]
    assert abs(out[0][0][1] - 0.6) < 1e-9 and abs(sum(p for _, p in out[0]) - 1) < 1e-9
    assert all(tok in ("<|en|>", "<|sw|>") for r in out for tok, _ in r)
    assert seen == {"sw", "en"}
    assert wrapped.is_multilingual is True  # everything else passes through


def _fake_whisper(monkeypatch, calls, windows=()):
    """A fake faster-whisper whose transcribe() runs one per-window language
    detection per entry in ``windows`` (each the top language that window's
    encoder output would score), like multilingual mode does."""
    import sys
    import types

    class Inner:
        is_multilingual = True

        def __init__(self):
            self.queue = list(windows)

        def detect_language(self, enc):
            top = self.queue.pop(0)
            return [[(f"<|{top}|>", 0.6), ("<|yo|>", 0.3), ("<|en|>" if top != "en" else "<|sw|>", 0.1)]]

    class FakeModel:
        def __init__(self, *a, **kw):
            self.model = Inner()

        def transcribe(self, samples, **kw):
            calls.append(kw)
            if kw.get("multilingual"):
                for _ in windows:
                    self.model.detect_language("encoder-output")
            seg = types.SimpleNamespace(text=" Habari, good morning.", words=None)
            return iter([seg]), types.SimpleNamespace(language="sw")

        def detect_language(self, samples, **kw):
            return "sw", 0.8, [("sw", 0.8), ("en", 0.2)]

    monkeypatch.setitem(sys.modules, "faster_whisper", types.SimpleNamespace(WhisperModel=FakeModel))
    monkeypatch.setitem(sys.modules, "faster_whisper.audio",
                        types.SimpleNamespace(decode_audio=lambda *a, **k: [0.1] * 16000))


def test_code_switching_redetects_language_per_window(monkeypatch):
    calls = []
    _fake_whisper(monkeypatch, calls, windows=("sw", "en", "sw"))
    from app.transcription import FasterWhisperProvider

    cfg = Config()
    cfg.transcribe_code_switch = "window"
    result = FasterWhisperProvider(cfg)._run(b"\x00" * 10, "meeting.webm")
    assert calls[0]["multilingual"] is True
    assert calls[0]["vad_filter"] is True and "clip_timestamps" not in calls[0]
    assert calls[0]["language"] == "sw"  # first window's language
    assert result.language == "sw+en"   # the meeting switched languages


def test_code_switching_off_when_pinned_or_disabled(monkeypatch):
    calls = []
    _fake_whisper(monkeypatch, calls)
    from app.transcription import FasterWhisperProvider

    cfg = Config()
    cfg.transcribe_code_switch = "off"
    FasterWhisperProvider(cfg)._run(b"\x00" * 10, "a.webm")
    cfg = Config()
    cfg.transcribe_language = "en"
    FasterWhisperProvider(cfg)._run(b"\x00" * 10, "b.webm")
    assert [c["multilingual"] for c in calls] == [False, False]
    assert calls[1]["language"] == "en"


def test_turns_mode_decodes_speech_clips_that_end_at_pauses(monkeypatch):
    """Default mode: VAD speech becomes clips ending at pauses, each with its own
    en/sw decision. Silence is still never decoded (only VAD clips are)."""
    calls = []
    _fake_whisper(monkeypatch, calls, windows=("en", "sw"))
    monkeypatch.setattr("app.transcription._speech_clips", lambda samples: [[0.5, 12.0], [13.4, 30.1]])
    from app.transcription import FasterWhisperProvider

    result = FasterWhisperProvider(Config())._run(b"\x00" * 10, "meeting.webm")
    assert calls[0]["multilingual"] is True
    assert calls[0]["vad_filter"] is False
    assert calls[0]["clip_timestamps"] == [0.5, 12.0, 13.4, 30.1]
    assert result.language == "sw+en"


def test_turns_mode_falls_back_to_vad_windows_without_clips(monkeypatch):
    calls = []
    _fake_whisper(monkeypatch, calls)
    monkeypatch.setattr("app.transcription._speech_clips", lambda samples: [])
    from app.transcription import FasterWhisperProvider

    FasterWhisperProvider(Config())._run(b"\x00" * 10, "meeting.webm")
    assert calls[0]["vad_filter"] is True and "clip_timestamps" not in calls[0]


def test_speech_clips_break_at_pauses_and_cap_at_30s(monkeypatch):
    import sys
    import types

    from app.transcription import _speech_clips

    sr = 16000
    stamps = [(0.0, 4.0), (4.3, 9.0),      # short gap: same clip
              (10.5, 14.0),                # 1.5 s pause: new clip
              (14.2, 45.0)]                # would exceed 30 s: new clip
    vad = types.SimpleNamespace(
        VadOptions=lambda **kw: kw,
        get_speech_timestamps=lambda samples, opts: [{"start": int(a * sr), "end": int(b * sr)} for a, b in stamps])
    monkeypatch.setitem(sys.modules, "faster_whisper.vad", vad)
    assert _speech_clips([0.0]) == [[0.0, 9.0], [10.5, 14.0], [14.2, 45.0]]


def test_code_switch_mode_aliases():
    from app.transcription import FasterWhisperProvider

    p = FasterWhisperProvider.__new__(FasterWhisperProvider)
    p._langs, p._cfg = object(), Config()
    for value, mode in (("true", "turns"), ("false", "off"), ("window", "window"), ("", "turns"), ("TURNS", "turns")):
        p._cfg.transcribe_code_switch = value
        assert p._code_switch_mode() == mode
    p._cfg.transcribe_language = "sw"
    assert p._code_switch_mode() == "off"


def _fake_vad(monkeypatch, stamps):
    import sys
    import types

    sr = 16000
    monkeypatch.setitem(sys.modules, "faster_whisper.vad", types.SimpleNamespace(
        VadOptions=lambda **kw: kw,
        get_speech_timestamps=lambda samples, opts: [{"start": int(a * sr), "end": int(b * sr)} for a, b in stamps]))


def test_uncovered_speech_finds_speech_with_no_words(monkeypatch):
    import types

    from app.transcription import _uncovered_speech

    # English 0-5 s (decoded), Swahili 5.6-10 s (no words came back), English 10.5-15 s (decoded),
    # and a 1 s blip that is too short to bother with.
    _fake_vad(monkeypatch, [(0.0, 5.0), (5.6, 10.0), (10.5, 15.0), (16.0, 17.0)])
    w = lambda a, b: types.SimpleNamespace(start=a, end=b)
    segs = [types.SimpleNamespace(start=0.0, end=5.0, words=[w(0.1, 2.0), w(2.1, 4.9)]),
            types.SimpleNamespace(start=10.5, end=15.0, words=[w(10.6, 12.0), w(12.1, 14.8)])]
    assert _uncovered_speech([0.0], segs) == [[5.6, 10.0]]


def test_recovered_speech_is_merged_in_time_order_and_low_confidence_dropped(monkeypatch):
    import types

    from app.transcription import FasterWhisperProvider

    seg = lambda a, b, text, lp=-0.3: types.SimpleNamespace(start=a, end=b, text=text, words=None, avg_logprob=lp,
                                                            no_speech_prob=0.1, compression_ratio=1.2)
    monkeypatch.setattr("app.transcription._uncovered_speech", lambda samples, segments: [[5.6, 10.0], [20.0, 22.0]])
    calls = []

    class Model:
        def transcribe(self, samples, **kw):
            calls.append(kw)
            return iter([seg(5.6, 10.0, " Mteja anasema shamba liliuzwa."), seg(20.0, 22.0, " Asante.", lp=-1.6)]), None

    p = FasterWhisperProvider.__new__(FasterWhisperProvider)
    p._model = Model()
    first = [seg(0.0, 5.0, " Good morning."), seg(10.5, 15.0, " We will file the plaint.")]
    out = p._recover_dropped_speech([0.0], first, {"language": "en", "vad_filter": True})
    assert [s.text.strip() for s in out] == ["Good morning.", "Mteja anasema shamba liliuzwa.", "We will file the plaint."]
    assert calls[0]["clip_timestamps"] == [5.6, 10.0, 20.0, 22.0]
    assert calls[0]["multilingual"] is True and calls[0]["vad_filter"] is False
