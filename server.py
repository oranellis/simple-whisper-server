import asyncio
import io
import logging
import os
from threading import Lock

from fastapi import FastAPI, File, Form, HTTPException, UploadFile, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from faster_whisper import WhisperModel
from streaming import StreamingTranscriber
from sessions import SessionNotFound, SessionStore


app = FastAPI(title="Faster Whisper")

model_name = "turbo" if os.environ.get("WHISPER_TURBO") else "large-v3"

print(f"Loading Faster Whisper {model_name} model...", flush=True)

model = WhisperModel(
    model_name,
    device="cuda",
    compute_type="float16",
)

print(f"Faster Whisper {model_name} model loaded.", flush=True)

model_lock = Lock()

print("Loading Faster Whisper large-v3-turbo model (for translation)...", flush=True)

translate_model = WhisperModel(
    "large-v3-turbo",
    device="cuda",
    compute_type="float16",
)

print("Faster Whisper large-v3-turbo model loaded.", flush=True)

translate_model_lock = Lock()
sessions = SessionStore(os.environ.get("RECORDINGS_DIR", "recordings"))

app.mount("/static", StaticFiles(directory="static"), name="static")


class CreateSessionRequest(BaseModel):
    name: str | None = None


class RenameSessionRequest(BaseModel):
    name: str


@app.get("/api/sessions")
def list_sessions():
    return sessions.list()


@app.post("/api/sessions")
def create_session(request: CreateSessionRequest):
    return sessions.create(request.name)


@app.get("/api/sessions/{session_id}")
def get_session(session_id: str):
    try:
        return sessions.get(session_id)
    except SessionNotFound:
        raise HTTPException(status_code=404, detail="Session not found")


@app.patch("/api/sessions/{session_id}")
def rename_session(session_id: str, request: RenameSessionRequest):
    name = request.name.strip()
    if not name:
        raise HTTPException(status_code=400, detail="Name must not be empty")
    try:
        return sessions.rename(session_id, name)
    except SessionNotFound:
        raise HTTPException(status_code=404, detail="Session not found")


def _transcribe_audio(audio_bytes, language, task, prompt, whisper_model, lock):
    with lock:
        segments, _ = whisper_model.transcribe(
            io.BytesIO(audio_bytes),
            language=language,
            task=task,
            initial_prompt=prompt or None,
            vad_filter=True,
        )
        return "".join(segment.text for segment in segments).strip()


async def _batch_transcribe(file, language, prompt, task, whisper_model, lock):
    audio_bytes = await file.read()
    if not audio_bytes:
        raise HTTPException(status_code=400, detail="Empty audio file")
    if language in (None, "", "auto"):
        language = None
    try:
        text = await asyncio.to_thread(
            _transcribe_audio, audio_bytes, language, task, prompt, whisper_model, lock
        )
    except Exception:
        logging.exception("Batch transcription failed")
        raise HTTPException(status_code=400, detail="Could not transcribe audio")
    return {"text": text}


# OpenAI Whisper API-compatible endpoints (https://platform.openai.com/docs/api-reference/audio),
# for clients such as Voxtype that transcribe via a remote server. `model` and
# `response_format` are accepted for compatibility but ignored: transcription
# always runs the loaded server model (see --turbo) and translation the
# loaded large-v3-turbo model, both returning JSON.
@app.post("/v1/audio/transcriptions")
async def transcribe_upload(
    file: UploadFile = File(...),
    model_name: str | None = Form(None, alias="model"),
    language: str | None = Form(None),
    prompt: str | None = Form(None),
    response_format: str | None = Form(None),
):
    return await _batch_transcribe(file, language, prompt, "transcribe", model, model_lock)


@app.post("/v1/audio/translations")
async def translate_upload(
    file: UploadFile = File(...),
    model_name: str | None = Form(None, alias="model"),
    prompt: str | None = Form(None),
    response_format: str | None = Form(None),
):
    return await _batch_transcribe(
        file, None, prompt, "translate", translate_model, translate_model_lock
    )


@app.websocket("/transcribe-stream")
async def transcribe_stream(socket: WebSocket):
    await socket.accept()
    language = socket.query_params.get("language", "en")
    session_id = socket.query_params.get("session_id")
    if not session_id:
        await socket.send_json({"type": "error", "message": "Missing session_id."})
        await socket.close(code=1008)
        return
    try:
        recording = sessions.open_segment(session_id, language)
    except SessionNotFound:
        await socket.send_json({"type": "error", "message": "Session not found."})
        await socket.close(code=1008)
        return
    except Exception:
        logging.exception("Could not start session recording")
        await socket.send_json({"type": "error", "message": "Could not save audio recording; check server logs."})
        await socket.close(code=1011)
        return
    logging.info("Recording live audio to %s", recording.path)
    reason = "stopped"
    queue = asyncio.Queue(maxsize=120)
    state = StreamingTranscriber(model, model_lock, language)

    async def receive():
        while True:
            message = await socket.receive()
            if message["type"] == "websocket.disconnect":
                raise WebSocketDisconnect()
            pcm = message.get("bytes")
            if pcm is not None:
                if len(pcm) > 32000 or len(pcm) % 2:
                    raise ValueError("Invalid PCM packet")
                recording.write(pcm)
                queue.put_nowait(pcm)
            elif message.get("text") == "stop":
                queue.put_nowait(None)
                return
            else:
                raise ValueError("Expected PCM audio or stop")

    async def transcribe():
        pending = bytearray()
        while True:
            packet = await queue.get()
            final = packet is None
            if packet:
                pending.extend(packet)
            if not final and len(pending) < 32000:
                continue
            # Coalesce packets accumulated during inference instead of
            # repeatedly decoding an increasingly stale one-second backlog.
            while not final and not queue.empty() and len(pending) < 160000:
                packet = queue.get_nowait()
                final = packet is None
                if packet:
                    pending.extend(packet)
            result = await asyncio.to_thread(state.process, bytes(pending), final)
            pending.clear()
            recording.event({"type": "recognition", "trace": state.last_trace,
                             "result": result})
            await socket.send_json(result)
            if final:
                return

    receiver = asyncio.create_task(receive())
    worker = asyncio.create_task(transcribe())
    try:
        done, _ = await asyncio.wait(
            [receiver, worker], return_when=asyncio.FIRST_COMPLETED
        )
        for task in done:
            task.result()
        if receiver in done:
            await worker
    except WebSocketDisconnect:
        reason = "disconnected"
    except asyncio.CancelledError:
        reason = "cancelled"
        raise
    except Exception as error:
        reason = "error"
        logging.exception("Live transcription failed")
        try:
            await socket.send_json({
                "type": "error",
                "message": "Audio backlog exceeded; please restart." if isinstance(error, asyncio.QueueFull)
                else "Live transcription failed; check the server logs.",
            })
        except (RuntimeError, WebSocketDisconnect):
            pass
    finally:
        receiver.cancel()
        worker.cancel()
        await asyncio.gather(receiver, worker, return_exceptions=True)
        try:
            recording.close(reason)
        except Exception:
            logging.exception("Could not finalize recording %s", recording.path)
        if state.committed:
            try:
                sessions.append_text(session_id, state.committed, language)
            except Exception:
                logging.exception("Could not update session transcript %s", session_id)
        try:
            await socket.close()
        except RuntimeError:
            pass


@app.get("/")
def index():
    return FileResponse("static/index.html")


@app.get("/health")
def health():
    return {
        "status": "ok",
        "model": model_name,
        "translate_model": "large-v3-turbo",
        "device": "cuda",
        "compute_type": "float16",
    }
