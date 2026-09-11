import asyncio
import logging
from threading import Lock

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from faster_whisper import WhisperModel
from streaming import StreamingTranscriber


app = FastAPI(title="Faster Whisper")

print("Loading Faster Whisper turbo model...", flush=True)

model = WhisperModel(
    "turbo",
    device="cuda",
    compute_type="float16",
)

print("Faster Whisper model loaded.", flush=True)

model_lock = Lock()

app.mount("/static", StaticFiles(directory="static"), name="static")


@app.websocket("/transcribe-stream")
async def transcribe_stream(socket: WebSocket):
    await socket.accept()
    queue = asyncio.Queue(maxsize=120)

    async def receive():
        while True:
            message = await socket.receive()
            if message["type"] == "websocket.disconnect":
                raise WebSocketDisconnect()
            pcm = message.get("bytes")
            if pcm is not None:
                if len(pcm) > 32000 or len(pcm) % 2:
                    raise ValueError("Invalid PCM packet")
                queue.put_nowait(pcm)
            elif message.get("text") == "stop":
                queue.put_nowait(None)
                return
            else:
                raise ValueError("Expected PCM audio or stop")

    async def transcribe():
        state = StreamingTranscriber(
            model, model_lock, socket.query_params.get("language", "en")
        )
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
        pass
    except Exception as error:
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
        "model": "turbo",
        "device": "cuda",
        "compute_type": "float16",
    }
