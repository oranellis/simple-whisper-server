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


if __name__ == "__main__":
    unittest.main()
