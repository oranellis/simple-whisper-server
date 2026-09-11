# Faster Whisper server

Install `requirements.txt` in your Python environment and run `./run.sh`
with a compatible CUDA setup. Microphone capture requires HTTPS or localhost.

Live capture sends continuous mono 16 kHz signed little-endian PCM through
`/transcribe-stream?language=en`. AudioWorklet packets contain 250 ms of audio;
they are transport packets, not independent transcription boundaries.
The server decodes the rolling audio roughly once per second, subject to GPU
speed, and commits a matching word prefix across two successive hypotheses.
The newest 500 ms remains provisional. Faint text in the UI may change.

Committed audio is trimmed with one second of overlap. At approximately
25 seconds of unresolved audio, the oldest hypothesis is finalized to keep
the buffer bounded; this fallback can be less accurate than stable agreement.
Stop flushes the remaining audio and final hypothesis before allowing restart.
Slow clients or excessive server backlogs receive an error instead of silently
dropping audio. Only live microphone transcription is supported; file uploads
and the legacy chunk-based POST endpoints have been removed.

This is a small local-agreement implementation inspired by
[Whisper-Streaming](https://github.com/ufal/whisper_streaming), not an integration
of that package. Recognition still runs on overlapping audio windows.

Run the model-independent tests with `python -m unittest test_streaming.py`.
