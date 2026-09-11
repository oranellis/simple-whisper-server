//
// Live transcription: continuous 16 kHz PCM over WebSocket.
//
const liveStart = document.getElementById("live-start");
const liveStop = document.getElementById("live-stop");
const liveLanguage = document.getElementById("live-language");
const liveStatus = document.getElementById("live-status");
const liveOutput = document.getElementById("live-output");
let session = null;

async function releaseAudio(s) {
    s.stream?.getTracks().forEach(track => track.stop());
    s.source?.disconnect();
    s.node?.disconnect();
    if (s.context && s.context.state !== "closed") await s.context.close();
}

async function fail(s, message) {
    if (session !== s) return;
    session = null;
    clearTimeout(s.timeout);
    s.socket?.close();
    await releaseAudio(s);
    liveStatus.textContent = message;
    liveStart.disabled = false;
    liveStop.disabled = true;
    liveLanguage.disabled = false;
}

async function startLive() {
    if (session) return;
    if (!window.isSecureContext || !navigator.mediaDevices?.getUserMedia) {
        liveStatus.textContent = "Microphone access requires HTTPS or localhost.";
        return;
    }
    const s = {};
    session = s;
    liveStart.disabled = true;
    liveLanguage.disabled = true;
    liveOutput.textContent = "";
    liveStatus.textContent = "Connecting...";
    try {
        s.stream = await navigator.mediaDevices.getUserMedia({
            audio: {channelCount: 1, echoCancellation: true, noiseSuppression: true,
                autoGainControl: true},
        });
        s.context = new AudioContext({sampleRate: 16000});
        if (s.context.sampleRate !== 16000) {
            throw new Error("This browser does not support 16 kHz audio capture.");
        }
        await s.context.audioWorklet.addModule("/static/pcm-worklet.js");
        await s.context.resume();
        const protocol = location.protocol === "https:" ? "wss:" : "ws:";
        s.socket = new WebSocket(
            protocol + "//" + location.host + "/transcribe-stream?language=" +
            encodeURIComponent(liveLanguage.value)
        );
        await new Promise((resolve, reject) => {
            s.timeout = setTimeout(() => reject(new Error("Connection timed out.")), 10000);
            s.socket.onopen = resolve;
            s.socket.onerror = () => reject(new Error("Could not connect to transcription server."));
            s.socket.onclose = () => reject(new Error("Connection closed."));
        });
        clearTimeout(s.timeout);
        s.socket.onmessage = async event => {
            if (session !== s) return;
            const result = JSON.parse(event.data);
            if (result.type === "error") {
                await fail(s, result.message);
                return;
            }
            liveOutput.replaceChildren(document.createTextNode(result.text));
            if (result.partial) {
                const partial = document.createElement("span");
                partial.style.opacity = "0.55";
                partial.textContent = result.partial;
                liveOutput.append(partial);
            }
            liveOutput.scrollTop = liveOutput.scrollHeight;
            if (result.type === "done") {
                await fail(s, "Stopped.");
            }
        };
        s.socket.onclose = () => fail(s, "Connection lost. Restart to continue.");
        s.socket.onerror = () => fail(s, "Transcription connection failed.");
        s.source = s.context.createMediaStreamSource(s.stream);
        s.node = new AudioWorkletNode(s.context, "pcm-capture");
        s.node.port.onmessage = event => {
            if (session !== s || s.socket.readyState !== WebSocket.OPEN) return;
            if (event.data === "flushed") {
                s.socket.send("stop");
                releaseAudio(s);
                s.timeout = setTimeout(() => fail(s, "Timed out finishing transcription."), 120000);
                return;
            }
            if (s.socket.bufferedAmount > 16000 * 2 * 10) {
                fail(s, "Connection too slow. Restart to continue.");
                return;
            }
            s.socket.send(event.data);
        };
        s.source.connect(s.node);
        // The worklet outputs silence, keeping capture active without feedback.
        s.node.connect(s.context.destination);
        liveStop.disabled = false;
        liveStatus.textContent = "Listening... Faint text may change.";
    } catch (error) {
        await fail(s, error.message);
    }
}

function stopLive() {
    if (!session?.node) return;
    liveStop.disabled = true;
    liveStatus.textContent = "Finishing transcription...";
    session.node.port.postMessage("stop");
}

liveStart.addEventListener("click", startLive);
liveStop.addEventListener("click", stopLive);
