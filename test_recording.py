import json
from pathlib import Path
import tempfile
import unittest
import wave

from recording import SessionRecording


class RecordingTests(unittest.TestCase):
    def test_packets_are_preserved_and_wav_finalized(self):
        for reason in ("stopped", "disconnected", "error", "cancelled"):
            with self.subTest(reason=reason), tempfile.TemporaryDirectory() as directory:
                recording = SessionRecording(Path(directory) / "sessions", "en")
                packets = [b"\x00\x00\xff\x7f", b"\x00\x80"]
                for packet in packets:
                    recording.write(packet)
                recording.event({"type": "recognition", "text": "comma"})
                recording.close(reason)
                with wave.open(str(recording.path), "rb") as audio:
                    self.assertEqual(audio.getnchannels(), 1)
                    self.assertEqual(audio.getsampwidth(), 2)
                    self.assertEqual(audio.getframerate(), 16000)
                    self.assertEqual(audio.getnframes(), 3)
                    self.assertEqual(audio.readframes(3), b"".join(packets))
                events = [json.loads(line) for line in
                          recording.path.with_suffix(".jsonl").read_text().splitlines()]
                self.assertEqual(events[-1]["reason"], reason)
                self.assertEqual(events[-1]["duration"], 3 / 16000)
                self.assertEqual(events[1]["text"], "comma")

    def test_sessions_have_unique_files_even_without_audio(self):
        with tempfile.TemporaryDirectory() as directory:
            first = SessionRecording(directory, "en")
            second = SessionRecording(directory, "en")
            first.close("stopped")
            second.close("stopped")
            self.assertNotEqual(first.path, second.path)
            with wave.open(str(first.path), "rb") as audio:
                self.assertEqual(audio.getnframes(), 0)
