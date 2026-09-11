//
// File transcription
//

const fileForm = document.getElementById("file-form");
const fileInput = document.getElementById("file");
const fileLanguage = document.getElementById("file-language");

const fileStatus = document.getElementById("file-status");
const fileOutput = document.getElementById("file-output");


fileForm.addEventListener("submit", async (event) => {
    event.preventDefault();

    const file = fileInput.files[0];

    if (!file) {
        fileStatus.textContent = "No file selected.";
        return;
    }

    const data = new FormData();

    data.append("file", file);
    data.append("language", fileLanguage.value);

    fileStatus.textContent = "Transcribing...";
    fileOutput.textContent = "";

    try {
        const response = await fetch("/transcribe", {
            method: "POST",
            body: data,
        });

        const result = await response.json();

        if (!response.ok) {
            throw new Error(
                result.detail || JSON.stringify(result)
            );
        }

        fileOutput.textContent = result.text;

        fileStatus.textContent =
            `Done - ${result.duration.toFixed(1)} seconds`;
    } catch (error) {
        fileStatus.textContent = "Transcription failed.";
        fileOutput.textContent = String(error);
    }
});


//
// Live transcription
//

const liveStart = document.getElementById("live-start");
const liveStop = document.getElementById("live-stop");
const liveLanguage = document.getElementById("live-language");

const liveStatus = document.getElementById("live-status");
const liveOutput = document.getElementById("live-output");

const CHUNK_DURATION = 4000;

let liveStream = null;
let liveRecorder = null;
let liveTimer = null;
let liveRunning = false;

let liveTranscript = "";
let liveQueue = Promise.resolve();


function chooseMimeType() {
    const types = [
        "audio/webm;codecs=opus",
        "audio/ogg;codecs=opus",
        "audio/webm",
        "audio/ogg",
    ];

    for (const type of types) {
        if (MediaRecorder.isTypeSupported(type)) {
            return type;
        }
    }

    return "";
}


async function startLive() {
    if (!window.isSecureContext) {
        liveStatus.textContent =
            "Microphone access requires HTTPS.";
        return;
    }

    if (!navigator.mediaDevices?.getUserMedia) {
        liveStatus.textContent =
            "Microphone access is not available.";
        return;
    }

    try {
        liveStream =
            await navigator.mediaDevices.getUserMedia({
                audio: {
                    channelCount: 1,
                    echoCancellation: true,
                    noiseSuppression: true,
                    autoGainControl: true,
                },
            });

        liveTranscript = "";
        liveOutput.textContent = "";

        liveQueue = Promise.resolve();
        liveRunning = true;

        liveStart.disabled = true;
        liveStop.disabled = false;

        liveStatus.textContent = "Listening...";

        recordNextChunk();
    } catch (error) {
        liveStatus.textContent =
            `Microphone error: ${error.message}`;
    }
}


function recordNextChunk() {
    if (!liveRunning) {
        return;
    }

    const mimeType = chooseMimeType();

    const options = {
        audioBitsPerSecond: 64000,
    };

    if (mimeType) {
        options.mimeType = mimeType;
    }

    const recorder = new MediaRecorder(
        liveStream,
        options
    );

    liveRecorder = recorder;

    const parts = [];

    recorder.addEventListener("dataavailable", (event) => {
        if (event.data.size > 0) {
            parts.push(event.data);
        }
    });

    recorder.addEventListener("stop", () => {
        if (parts.length > 0) {
            const blob = new Blob(parts, {
                type: recorder.mimeType,
            });

            queueLiveChunk(
                blob,
                recorder.mimeType
            );
        }

        if (liveRunning) {
            recordNextChunk();
        } else {
            finishLive();
        }
    });

    recorder.start();

    liveTimer = setTimeout(() => {
        if (recorder.state === "recording") {
            recorder.stop();
        }
    }, CHUNK_DURATION);
}


function queueLiveChunk(blob, mimeType) {
    liveQueue = liveQueue
        .then(() => transcribeLiveChunk(blob, mimeType))
        .catch((error) => {
            console.error(error);

            liveStatus.textContent =
                `Chunk failed: ${error.message}`;
        });
}


async function transcribeLiveChunk(blob, mimeType) {
    let extension = "webm";

    if (mimeType.includes("ogg")) {
        extension = "ogg";
    }

    const data = new FormData();

    data.append(
        "file",
        blob,
        `live.${extension}`
    );

    data.append(
        "language",
        liveLanguage.value
    );

    // Give Whisper some preceding context.
    data.append(
        "prompt",
        liveTranscript.slice(-500)
    );

    const response = await fetch("/transcribe-live", {
        method: "POST",
        body: data,
    });

    const result = await response.json();

    if (!response.ok) {
        throw new Error(
            result.detail || JSON.stringify(result)
        );
    }

    const text = result.text.trim();

    if (text) {
        if (liveTranscript) {
            liveTranscript += " ";
        }

        liveTranscript += text;

        liveOutput.textContent = liveTranscript;

        liveOutput.scrollTop =
            liveOutput.scrollHeight;
    }

    if (liveRunning) {
        liveStatus.textContent = "Listening...";
    }
}


function stopLive() {
    liveRunning = false;

    liveStart.disabled = false;
    liveStop.disabled = true;

    liveStatus.textContent =
        "Finishing transcription...";

    if (liveTimer) {
        clearTimeout(liveTimer);
        liveTimer = null;
    }

    if (
        liveRecorder &&
        liveRecorder.state === "recording"
    ) {
        liveRecorder.stop();
    } else {
        finishLive();
    }
}


function finishLive() {
    if (liveStream) {
        for (const track of liveStream.getTracks()) {
            track.stop();
        }

        liveStream = null;
    }

    liveQueue.then(() => {
        liveStatus.textContent = "Stopped.";
    });
}


liveStart.addEventListener(
    "click",
    startLive
);

liveStop.addEventListener(
    "click",
    stopLive
);
