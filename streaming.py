"""Rolling PCM transcription with agreement between consecutive hypotheses."""

import numpy as np

SAMPLE_RATE = 16000


class StreamingTranscriber:
    def __init__(self, model, lock, language="en"):
        self.model = model
        self.lock = lock
        self.language = language or None
        self.audio = np.empty(0, dtype=np.float32)
        self.offset = 0.0
        self.committed_end = 0.0
        self.committed = ""
        self.previous = []

    def process(self, pcm, final=False):
        samples = np.frombuffer(pcm, dtype="<i2").astype(np.float32) / 32768
        self.audio = np.concatenate((self.audio, samples))
        if not len(self.audio):
            return self.result(final)
        with self.lock:
            segments, _ = self.model.transcribe(
                self.audio,
                language=self.language,
                beam_size=1,
                vad_filter=True,
                word_timestamps=True,
                initial_prompt=self.committed[-500:] or None,
                condition_on_previous_text=False,
            )
            segments = list(segments)
        words = [
            (w.start + self.offset, w.end + self.offset, w.word)
            for s in segments for w in (s.words or [])
            if w.end + self.offset > self.committed_end + 0.05
        ]
        count = 0
        # Never commit the newest edge: the next packet may complete a word.
        safe_end = self.offset + len(self.audio) / SAMPLE_RATE - 0.5
        for old, new in zip(self.previous, words):
            if (old[2].strip() != new[2].strip()
                    or abs(old[0] - new[0]) > 1.0 or new[1] > safe_end):
                break
            count += 1
        if final:
            count = len(words)
        self.commit(words[:count])
        self.previous = words[count:]

        # Retain acoustic context behind committed words. Under prolonged
        # disagreement, finalize the oldest hypothesis to bound memory/latency.
        end = self.offset + len(self.audio) / SAMPLE_RATE
        cut = max(self.offset, self.committed_end - 1.0)
        if end - cut > 25:
            forced = [w for w in self.previous if w[1] <= end - 20]
            self.commit(forced)
            self.previous = self.previous[len(forced):]
            cut = max(cut, forced[-1][1] if forced else end - 25)
            # Avoid cutting through a recognized, still-provisional word.
            if self.previous:
                cut = min(cut, self.previous[0][0])
        remove = max(0, min(len(self.audio), int((cut - self.offset) * SAMPLE_RATE)))
        self.audio = self.audio[remove:].copy()
        self.offset += remove / SAMPLE_RATE
        return self.result(final)

    def commit(self, words):
        if words:
            self.committed += "".join(w[2] for w in words)
            self.committed_end = words[-1][1]

    def result(self, final):
        return {
            "type": "done" if final else "transcript",
            "text": self.committed.lstrip(),
            "partial": "".join(w[2] for w in self.previous),
        }
