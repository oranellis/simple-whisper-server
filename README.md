# Faster Whisper server

Install `requirements.txt` in your Python environment and run `./run.sh`
with a compatible CUDA setup. Microphone capture requires HTTPS or localhost.

The web UI organizes recordings into sessions, listed on the left. Create a
session, then start and stop the microphone any number of times within it;
each recording appends to that session's transcript. Sessions can be renamed
from the list. The session REST API: `GET /api/sessions` lists sessions
(id, name, language, timestamps, and a short text preview), `POST
/api/sessions` creates one (`{"name": "..."}`, name optional), `GET
/api/sessions/{id}` returns the full session including its transcript, and
`PATCH /api/sessions/{id}` with `{"name": "..."}` renames it.

Live capture sends continuous mono 16 kHz signed little-endian PCM through
`/transcribe-stream?language=en&session_id=<id>`, where `session_id` is an
existing session's id. AudioWorklet packets contain 250 ms of audio;
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
dropping audio.

## OpenAI Whisper API-compatible endpoints

`POST /v1/audio/transcriptions` and `POST /v1/audio/translations` accept a
single audio file (`multipart/form-data`, field `file`) and run one batch
transcription with the same loaded turbo (large-v3-turbo) model, no session
required. They match enough of the [OpenAI audio API](
https://platform.openai.com/docs/api-reference/audio) shape for clients such
as [Voxtype](https://voxtype.io/) that transcribe via a remote server:
`model` and `response_format` are accepted but ignored (the response is
always `{"text": "..."}`); `language` is optional (omitted or `"auto"` lets
Whisper detect it); `prompt` is passed through as the initial prompt.
`/translations` always translates to English and ignores `language`. Point
Voxtype's `remote_endpoint` at this server's base URL (e.g.
`http://<host>:8000`) with `mode = "remote"`.

This is a small local-agreement implementation inspired by
[Whisper-Streaming](https://github.com/ufal/whisper_streaming), not an integration
of that package. Recognition still runs on overlapping audio windows.

Run the model-independent tests with `python -m unittest test_streaming.py`.

Each session is stored under `recordings/<UTC-time>-<unique-id>/` on the
server. Set `RECORDINGS_DIR` to change the base directory. `meta.json` holds
the session's name, language, accumulated transcript text, and timestamps.
Every start/stop recording within the session is a separate segment under
`segments/<UTC-time>-<unique-id>.wav` (16 kHz mono, 16-bit PCM) with a
matching `.jsonl` file. The directory must be writable; recording failures
stop the in-progress recording. Audio is written as received, including
packets waiting for transcription. Stop, disconnect, and handled errors
finalize the segment's WAV file, and its committed transcript is appended to
the session's `meta.json`.

Each segment's `.jsonl` file stores language, raw and filtered word
hypotheses with timestamps in seconds from that segment's start, displayed
transcript updates, and the segment's end reason. Use both files to
investigate repeated words. Each word entry is `[start_seconds, end_seconds,
text]`; timestamps remain relative to the segment's own start even after the
recognition buffer is trimmed. Recordings stay on disk until manually
removed; no automatic retention limit is configured. The default recordings
directory is ignored by Git and is not served by the web app. Run all tests
with `python -m unittest discover`.

## Installation

Install the service with
```
sudo ln -s "$(pwd)/whisper-server.service" /etc/systemd/system/
```
