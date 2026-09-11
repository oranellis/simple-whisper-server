from threading import Lock

from fastapi import FastAPI, UploadFile, File, Form
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from faster_whisper import WhisperModel


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


@app.post("/transcribe")
def transcribe(
    file: UploadFile = File(...),
    language: str = Form("en"),
):
    file.file.seek(0)

    with model_lock:
        segments, info = model.transcribe(
            file.file,
            language=language or None,
            beam_size=5,
            vad_filter=True,
            word_timestamps=True,
        )

        segments = list(segments)

    result_segments = []

    for segment in segments:
        result_segments.append(
            {
                "start": segment.start,
                "end": segment.end,
                "text": segment.text,
                "words": [
                    {
                        "start": word.start,
                        "end": word.end,
                        "word": word.word,
                        "probability": word.probability,
                    }
                    for word in (segment.words or [])
                ],
            }
        )

    return {
        "filename": file.filename,
        "language": info.language,
        "language_probability": info.language_probability,
        "duration": info.duration,
        "text": "".join(
            segment.text for segment in segments
        ).strip(),
        "segments": result_segments,
    }


@app.post("/transcribe-live")
def transcribe_live(
    file: UploadFile = File(...),
    language: str = Form("en"),
    prompt: str = Form(""),
):
    file.file.seek(0)

    with model_lock:
        segments, info = model.transcribe(
            file.file,
            language=language or None,
            beam_size=1,
            vad_filter=True,
            initial_prompt=prompt or None,
            word_timestamps=False,
        )

        segments = list(segments)

    text = "".join(
        segment.text for segment in segments
    ).strip()

    return {
        "text": text,
        "language": info.language,
        "duration": info.duration,
    }
