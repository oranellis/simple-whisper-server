# Faster Whisper server

Install `requirements.txt` in your Python environment and run `./run.sh`
with a compatible CUDA setup. Microphone capture requires HTTPS or localhost.

Live capture sends continuous mono 16 kHz signed little-endian PCM through
`/transcribe-stream?language=en`. AudioWorklet packets contain 250 ms of audio;
they are transport packets, not independent transcription boundaries.
The server decodes the rolling audio roughly once per second, subject to GPU
speed, and commits a matching word prefix across two successive hypotheses.
The newest 500 ms remains provisional. Faint text in the UI may change.
Overlap matching uses word text and overlapping timestamps to suppress words
already committed, including timestamp and punctuation changes. Large start-time
shifts are accepted when end times stay close and word intervals substantially
overlap, accounting for silence removed by buffer trimming. Separate
spoken repetitions are retained. Prompt context includes only trimmed audio.

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

Every live session is recorded to `recordings/<UTC-time>-<unique-id>.wav`
on the server (16 kHz mono, 16-bit PCM). Set `RECORDINGS_DIR` to change the
directory. The directory must be writable; recording failures stop the session.
Audio is written as received, including packets waiting for transcription.
Stop, disconnect, and handled errors finalize the WAV file.

A matching `.jsonl` file stores language, raw and filtered word hypotheses
with timestamps in seconds from recording start, displayed transcript updates,
and the session end reason. Use both files to investigate repeated words.
Each word entry is `[start_seconds, end_seconds, text]`; timestamps remain
relative to the full recording even after the recognition buffer is trimmed.
Recordings stay on disk until manually removed; no automatic retention limit
is configured. The default recordings directory is ignored by Git and is not
served by the web app. Run all tests with `python -m unittest discover`.

## Installation

Install the service with
```
sudo ln -s "$(pwd)/whisper-server.service" /etc/systemd/system/
```
