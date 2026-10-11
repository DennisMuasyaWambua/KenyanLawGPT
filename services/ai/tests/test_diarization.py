"""Speaker attribution: aligning Whisper word timings to diarized turns."""
from app.config import Config
from app.diarization import Turn, Word, assign_speakers, format_transcript, make_diarizer


def _w(start, end, text):
    return Word(start, end, text)


def test_words_follow_turns_and_merge_into_utterances():
    turns = [Turn(0.0, 2.8, 7), Turn(2.8, 7.8, 3), Turn(7.8, 11.0, 7)]
    words = [_w(0.0, 0.5, " Habari"), _w(0.6, 1.2, " wakili."),
             _w(3.0, 3.5, " Karibu,"), _w(3.6, 4.0, " keti."),
             _w(8.0, 8.4, " Asante.")]
    out = assign_speakers(words, turns)
    # Raw cluster ids (7, 3) are renumbered 1, 2 in order of first appearance.
    assert out == [
        {"speaker": 1, "start": 0.0, "end": 1.2, "text": "Habari wakili."},
        {"speaker": 2, "start": 3.0, "end": 4.0, "text": "Karibu, keti."},
        {"speaker": 1, "start": 8.0, "end": 8.4, "text": "Asante."},
    ]


def test_word_spanning_a_boundary_goes_to_the_larger_overlap():
    turns = [Turn(0.0, 1.0, 0), Turn(1.0, 3.0, 1)]
    out = assign_speakers([_w(0.9, 1.6, " sawa")], turns)
    assert out[0]["speaker"] == 1 and len({u["speaker"] for u in out}) == 1


def test_word_in_a_gap_goes_to_the_nearer_turn():
    turns = [Turn(0.0, 1.0, 0), Turn(5.0, 6.0, 1)]
    out = assign_speakers([_w(0.2, 0.6, " one"), _w(1.1, 1.3, " two"), _w(4.7, 4.9, " three")], turns)
    assert [(u["speaker"], u["text"]) for u in out] == [(1, "one two"), (2, "three")]


def test_zero_length_word_inside_a_turn_is_attributed_to_it():
    turns = [Turn(0.0, 2.0, 0), Turn(2.0, 4.0, 1)]
    out = assign_speakers([_w(0.5, 1.0, " Yes"), _w(3.0, 3.0, " no")], turns)
    assert [(u["speaker"], u["text"]) for u in out] == [(1, "Yes"), (2, "no")]


def test_overlapping_turns_with_long_earlier_turn():
    # Turn ends are not monotonic when speech overlaps; a long earlier turn must
    # still be found for a word well inside it.
    turns = [Turn(0.0, 10.0, 0), Turn(1.0, 2.0, 1), Turn(9.5, 12.0, 1)]
    out = assign_speakers([_w(5.0, 5.5, " still"), _w(11.0, 11.5, " me")], turns)
    assert [(u["speaker"], u["text"]) for u in out] == [(1, "still"), (2, "me")]


def test_nothing_to_attribute():
    assert assign_speakers([], [Turn(0, 1, 0)]) == []
    assert assign_speakers([_w(0, 1, " hi")], []) == []


def test_format_transcript_labels_and_clock():
    text = format_transcript([
        {"speaker": 1, "start": 5.2, "end": 7.0, "text": "Good morning."},
        {"speaker": 2, "start": 3725.0, "end": 3726.0, "text": "Morning."},
    ])
    assert text == "[00:05] Speaker 1: Good morning.\n[1:02:05] Speaker 2: Morning."


def test_missing_models_disable_diarization_instead_of_failing(tmp_path):
    cfg = Config()
    cfg.diarization_segmentation_model = str(tmp_path / "nope.onnx")
    assert make_diarizer(cfg) is None
    cfg.diarization_enabled = False
    assert make_diarizer(cfg) is None


def test_stranded_sentence_start_rejoins_its_speaker():
    turns = [Turn(0.0, 3.0, 0), Turn(3.0, 3.4, 1), Turn(3.4, 6.0, 0), Turn(6.0, 8.0, 1)]
    words = [_w(0.0, 1.0, " Yeah."), _w(3.1, 3.3, " You"), _w(3.5, 4.0, " can"),
             _w(4.1, 5.0, " put it there."), _w(6.1, 7.0, " Right.")]
    out = assign_speakers(words, turns)
    assert [(u["speaker"], u["text"]) for u in out] == [
        (1, "Yeah. You can put it there."), (2, "Right.")]


def test_short_complete_replies_are_not_moved():
    turns = [Turn(0.0, 1.0, 0), Turn(1.0, 3.0, 1)]
    out = assign_speakers([_w(0.1, 0.5, " Yes."), _w(1.2, 2.0, " then we file.")], turns)
    assert [(u["speaker"], u["text"]) for u in out] == [(1, "Yes."), (2, "then we file.")]


def test_numbering_restarts_at_one_when_first_fragment_moves():
    turns = [Turn(0.0, 0.4, 3), Turn(0.4, 3.0, 8)]
    out = assign_speakers([_w(0.0, 0.3, " So"), _w(0.5, 2.0, " we agreed.")], turns)
    assert out == [{"speaker": 1, "start": 0.0, "end": 2.0, "text": "So we agreed."}]
