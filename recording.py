"""Persist received session audio and recognition diagnostics locally."""

from contextlib import ExitStack
from datetime import datetime, timezone
import json
from pathlib import Path
from uuid import uuid4
import wave


class SessionRecording:
    def __init__(self, directory, language):
        directory = Path(directory)
        directory.mkdir(parents=True, exist_ok=True)
        self.id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ") + "-" + uuid4().hex
        self.path = directory / (self.id + ".wav")
        self.samples = 0
        self.files = ExitStack()
        try:
            audio = self.files.enter_context(self.path.open("xb"))
            self.wav = self.files.enter_context(wave.open(audio, "wb"))
            self.wav.setparams((1, 2, 16000, 0, "NONE", "not compressed"))
            self.events = self.files.enter_context(
                self.path.with_suffix(".jsonl").open("x", encoding="utf-8")
            )
            self.event({"type": "start", "language": language,
                        "sample_rate": 16000, "channels": 1})
        except BaseException:
            self.files.close()
            raise

    def write(self, pcm):
        if len(pcm) % 2:
            raise ValueError("PCM must contain complete 16-bit samples")
        # Update the WAV header after each packet, including interrupted sessions.
        self.wav.writeframes(pcm)
        self.samples += len(pcm) // 2

    def event(self, data):
        self.events.write(json.dumps(data, ensure_ascii=False) + "\n")
        self.events.flush()

    def close(self, reason):
        try:
            self.event({"type": "end", "reason": reason,
                        "duration": self.samples / 16000})
        finally:
            self.files.close()
