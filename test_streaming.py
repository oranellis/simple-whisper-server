import unittest
from threading import Lock
from types import SimpleNamespace

from streaming import SAMPLE_RATE, StreamingTranscriber


class FakeModel:
    def __init__(self, results):
        self.results = iter(results)

    def transcribe(self, audio, **kwargs):
        words = [SimpleNamespace(start=a, end=b, word=t)
                 for a, b, t in next(self.results)]
        return iter([SimpleNamespace(words=words)]), None


def pcm(seconds):
    return bytes(int(SAMPLE_RATE * seconds) * 2)


class StreamingTests(unittest.TestCase):
    def test_agreement_and_corrected_boundary(self):
        state = StreamingTranscriber(FakeModel([
            [(0, .4, " Hello"), (.5, .9, " wor")],
            [(0, .4, " Hello"), (.5, 1.2, " world")],
            [(0, .4, " Hello"), (.5, 1.2, " world")],
        ]), Lock())
        self.assertEqual(state.process(pcm(1))["text"], "")
        result = state.process(pcm(1))
        self.assertEqual(result["text"], "Hello")
        self.assertEqual(result["partial"], " world")
        result = state.process(pcm(1))
        self.assertEqual(result["text"], "Hello world")
        self.assertEqual(result["partial"], "")

    def test_stop_flushes_short_utterance(self):
        state = StreamingTranscriber(FakeModel([
            [(0, .2, " Hi")],
        ]), Lock())
        self.assertEqual(state.process(pcm(.3), final=True),
                         {"type": "done", "text": "Hi", "partial": ""})

    def test_silence_memory_is_bounded(self):
        state = StreamingTranscriber(FakeModel([[]] * 60), Lock())
        for _ in range(60):
            state.process(pcm(1))
        self.assertLessEqual(len(state.audio), SAMPLE_RATE * 25)
        self.assertEqual(state.committed, "")

    def test_trim_preserves_absolute_timestamps_and_no_duplicates(self):
        state = StreamingTranscriber(FakeModel([
            [(2, 3, " first")],
            [(2, 3, " first")],
            [(0, 1, " first"), (1.2, 2, " second")],
        ]), Lock())
        state.process(pcm(4))
        state.process(pcm(1))
        self.assertEqual(state.offset, 2)
        result = state.process(pcm(1), final=True)
        self.assertEqual(result["text"], "first second")

    def test_empty_stop(self):
        state = StreamingTranscriber(FakeModel([]), Lock())
        self.assertEqual(state.process(b"", final=True)["type"], "done")

    def test_drifting_last_word_does_not_reappear(self):
        state = StreamingTranscriber(FakeModel([
            [(0, .4, " Hello")],
            [(0, .4, " Hello")],
            [(0, .5, " Hello")],
            [(0, .5, " Hello")],
        ]), Lock())
        state.process(pcm(1))
        state.process(pcm(1))
        for final in (False, True):
            result = state.process(pcm(1), final=final)
            self.assertEqual(result["text"], "Hello")
            self.assertEqual(result["partial"], "")

    def test_drifting_phrase_after_trim_and_punctuation_change(self):
        state = StreamingTranscriber(FakeModel([
            [(2, 2.4, " Hello"), (2.4, 3, " world")],
            [(2, 2.4, " Hello"), (2.4, 3, " world")],
            [(0, .5, " hello,"), (.4, 1.2, " world."),
             (1.3, 1.8, " Again")],
        ]), Lock())
        state.process(pcm(4))
        state.process(pcm(1))
        result = state.process(pcm(1), final=True)
        self.assertEqual(result["text"], "Hello world Again")

    def test_real_repetition_survives_drifting_overlap(self):
        state = StreamingTranscriber(FakeModel([
            [(0, .4, " very")],
            [(0, .4, " very")],
            [(0, .5, " very"), (.45, .8, " very"), (.8, 1.2, " good")],
            [(0, .5, " very"), (.45, .8, " very"), (.8, 1.2, " good")],
        ]), Lock())
        state.process(pcm(1))
        state.process(pcm(1))
        self.assertEqual(state.process(pcm(1))["partial"], " very good")
        self.assertEqual(state.process(pcm(1))["text"], "very very good")

    def test_later_identical_word_without_overlap_survives(self):
        state = StreamingTranscriber(FakeModel([
            [(0, .4, " yes")],
            [(0, .4, " yes")],
            [(1, 1.4, " yes")],
        ]), Lock())
        state.process(pcm(1))
        state.process(pcm(1))
        self.assertEqual(state.process(pcm(1), final=True)["text"], "yes yes")

    def test_prompt_contains_only_audio_trimmed_away(self):
        model = FakeModel([
            [(0, .4, " Hello")],
            [(0, .4, " Hello")],
            [(0, .4, " Hello"), (2, 2.4, " world")],
        ])
        state = StreamingTranscriber(model, Lock())
        state.process(pcm(1))
        state.process(pcm(1))
        self.assertEqual(state.prompt, "")
        state.process(pcm(1), final=True)
        self.assertEqual(state.prompt, " Hello")
        self.assertEqual([w[2] for w in state.committed_words], [" world"])

    def test_trace_preserves_raw_duplicates_and_absolute_times(self):
        state = StreamingTranscriber(FakeModel([
            [(2, 3, " comma")],
            [(2, 3, " comma")],
            [(0, 1.1, " Comma."), (1.2, 1.6, " next")],
        ]), Lock())
        state.process(pcm(4))
        state.process(pcm(1))
        state.process(pcm(1), final=True)
        trace = state.last_trace
        self.assertEqual(trace["buffer_start"], 2)
        self.assertEqual(trace["buffer_end"], 6)
        self.assertEqual(trace["committed_end"], 3)
        self.assertEqual(trace["raw_words"],
                         [(2, 3.1, " Comma."), (3.2, 3.6, " next")])
        self.assertEqual(trace["filtered_words"], [(3.2, 3.6, " next")])

    def test_recorded_comma_start_shift_after_trimming(self):
        # Recorded hypothesis: a long silence was included in the first
        # word's start time, then excluded after the audio buffer was trimmed.
        state = StreamingTranscriber(FakeModel([
            [(2.529875, 4.849875, " comma")],
            [(2.529875, 4.849875, " comma")],
            [(.43, 1.23, " Comma.")],
            [(.43, 1.23, " Comma.")],
            [(.43, 1.23, " Comma.")],
        ]), Lock())
        state.process(pcm(5))
        self.assertEqual(state.process(pcm(1))["text"], "comma")
        self.assertAlmostEqual(state.offset, 3.849875)
        for final in (False, False, True):
            result = state.process(pcm(1), final=final)
            self.assertEqual(result["text"], "comma")
            self.assertEqual(result["partial"], "")

    def test_repeat_with_small_boundary_overlap_is_not_removed(self):
        state = StreamingTranscriber(None, Lock())
        state.commit([(2.529875, 4.849875, " comma")])
        repeated = (4.799875, 5.149875, " comma")
        self.assertEqual(state.remove_committed_overlap([repeated]), [repeated])

    def test_large_start_shift_matches_only_one_occurrence(self):
        state = StreamingTranscriber(None, Lock())
        state.commit([(2.529875, 4.849875, " comma")])
        replay = (4.279875, 5.079875, " Comma.")
        repeated = (5.1, 5.5, " comma")
        self.assertEqual(state.remove_committed_overlap([replay, repeated]), [repeated])


if __name__ == "__main__":
    unittest.main()
