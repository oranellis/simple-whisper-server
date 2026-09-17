//
// Recording sessions: a persistent list on the left, live transcription
// (continuous 16 kHz PCM over WebSocket) into the selected session on the right.
//
const sidebar = document.querySelector(".sidebar");
const newSessionButton = document.getElementById("new-session");
const sessionListEl = document.getElementById("session-list");
const emptyState = document.getElementById("empty-state");
const sessionView = document.getElementById("session-view");
const sessionNameLabel = document.getElementById("session-name");

const liveStart = document.getElementById("live-start");
const liveStop = document.getElementById("live-stop");
const liveLanguage = document.getElementById("live-language");
const liveStatus = document.getElementById("live-status");
const liveOutput = document.getElementById("live-output");

let sessionsList = [];
let currentSession = null; // {id, name, language, text, created_at, updated_at}
let live = null; // in-progress recording connection, if any

// -- API helpers ------------------------------------------------------------

async function apiGet(path) {
    const response = await fetch(path);
    if (!response.ok) throw new Error("Request failed");
    return response.json();
}

async function apiSend(method, path, body) {
    const response = await fetch(path, {
        method,
        headers: {"Content-Type": "application/json"},
        body: JSON.stringify(body),
    });
    if (!response.ok) throw new Error("Request failed");
    return response.json();
}

// -- Session list -------------------------------------------------------

function formatTimestamp(iso) {
    if (!iso) return "";
    const date = new Date(iso);
    if (Number.isNaN(date.getTime())) return "";
    return date.toLocaleString(undefined, {
        month: "short", day: "numeric", hour: "2-digit", minute: "2-digit",
    });
}

function renderSessionList() {
    sessionListEl.replaceChildren();
    for (const item of sessionsList) {
        const li = document.createElement("li");
        li.className = "session-item" + (currentSession?.id === item.id ? " active" : "");

        const selectRow = document.createElement("div");
        selectRow.className = "session-select";
        selectRow.setAttribute("role", "button");
        selectRow.tabIndex = 0;
        selectRow.addEventListener("click", () => selectSession(item.id));
        selectRow.addEventListener("keydown", event => {
            if (event.key === "Enter" || event.key === " ") {
                event.preventDefault();
                selectSession(item.id);
            }
        });

        const name = document.createElement("span");
        name.className = "session-item-name";
        name.textContent = item.name;

        const meta = document.createElement("span");
        meta.className = "session-item-meta";
        meta.textContent = formatTimestamp(item.updated_at);

        selectRow.append(name, meta);

        const renameButton = document.createElement("button");
        renameButton.type = "button";
        renameButton.className = "session-rename";
        renameButton.title = "Rename session";
        renameButton.textContent = "✎";
        renameButton.addEventListener("click", event => {
            event.stopPropagation();
            beginRename(li, item);
        });

        li.append(selectRow, renameButton);
        sessionListEl.append(li);
    }
}

function beginRename(li, item) {
    if (li.querySelector(".session-rename-input")) return;
    const nameSpan = li.querySelector(".session-item-name");
    const input = document.createElement("input");
    input.type = "text";
    input.className = "session-rename-input";
    input.value = item.name;
    nameSpan.replaceWith(input);
    input.addEventListener("click", event => event.stopPropagation());
    input.addEventListener("mousedown", event => event.stopPropagation());
    input.focus();
    input.select();

    let settled = false;
    const commit = async () => {
        if (settled) return;
        settled = true;
        const name = input.value.trim();
        if (!name || name === item.name) {
            renderSessionList();
            return;
        }
        try {
            const updated = await apiSend("PATCH", `/api/sessions/${item.id}`, {name});
            item.name = updated.name;
            item.updated_at = updated.updated_at;
            if (currentSession?.id === item.id) {
                currentSession.name = updated.name;
                sessionNameLabel.textContent = updated.name;
            }
        } catch (error) {
            liveStatus.textContent = "Could not rename session.";
        }
        renderSessionList();
    };
    input.addEventListener("keydown", event => {
        if (event.key === "Enter") input.blur();
        if (event.key === "Escape") {
            settled = true;
            renderSessionList();
        }
    });
    input.addEventListener("blur", commit);
}

function updateSessionSummary(session) {
    const entry = sessionsList.find(s => s.id === session.id);
    if (entry) {
        entry.updated_at = session.updated_at;
        entry.preview = (session.text || "").slice(0, 120);
        sessionsList.sort((a, b) => (b.updated_at || "").localeCompare(a.updated_at || ""));
    }
    renderSessionList();
}

async function loadSessions() {
    try {
        sessionsList = await apiGet("/api/sessions");
    } catch (error) {
        sessionsList = [];
    }
    renderSessionList();
}

async function createSession() {
    if (live) return;
    try {
        const created = await apiSend("POST", "/api/sessions", {});
        sessionsList.unshift({
            id: created.id, name: created.name, language: created.language,
            created_at: created.created_at, updated_at: created.updated_at, preview: "",
        });
        currentSession = created;
        renderSessionList();
        showSessionView();
    } catch (error) {
        liveStatus.textContent = "Could not create session.";
    }
}

async function selectSession(id) {
    if (live || currentSession?.id === id) return;
    try {
        currentSession = await apiGet(`/api/sessions/${id}`);
        renderSessionList();
        showSessionView();
    } catch (error) {
        liveStatus.textContent = "Could not load session.";
    }
}

// -- Session pane ---------------------------------------------------------

function showSessionView() {
    emptyState.hidden = true;
    sessionView.hidden = false;
    sessionNameLabel.textContent = currentSession.name;
    liveLanguage.value = currentSession.language || "en";
    liveStatus.textContent = "Ready";
    liveStart.disabled = false;
    liveStop.disabled = true;
    renderIdleTranscript();
}

function joinText(a, b) {
    if (!a) return b || "";
    if (!b) return a;
    return a + (/\s$/.test(a) ? "" : " ") + b;
}

function renderIdleTranscript() {
    liveOutput.replaceChildren(document.createTextNode(currentSession.text || ""));
}

function renderTranscript(segmentText, partial) {
    liveOutput.replaceChildren(document.createTextNode(joinText(currentSession.text, segmentText)));
    if (partial) {
        const span = document.createElement("span");
        span.className = "partial";
        span.textContent = partial;
        liveOutput.append(span);
    }
    liveOutput.scrollTop = liveOutput.scrollHeight;
}

function setRecordingLock(active) {
    sidebar.classList.toggle("recording", active);
    newSessionButton.disabled = active;
}

// -- Live recording ---------------------------------------------------------

async function releaseAudio(s) {
    s.stream?.getTracks().forEach(track => track.stop());
    s.source?.disconnect();
    s.node?.disconnect();
    if (s.context && s.context.state !== "closed") await s.context.close();
}

async function fail(s, message, {resync = true} = {}) {
    if (live !== s) return;
    live = null;
    clearTimeout(s.timeout);
    s.socket?.close();
    await releaseAudio(s);
    liveStatus.textContent = message;
    liveStart.disabled = false;
    liveStop.disabled = true;
    liveLanguage.disabled = false;
    setRecordingLock(false);
    // A clean "done" message already carries the final committed text; other
    // exit paths (disconnect, error, timeout) may leave the client stale
    // relative to text the server persisted before the connection dropped.
    if (resync) await syncSessionAfterRecording(s.sessionId);
}

async function syncSessionAfterRecording(sessionId) {
    try {
        const refreshed = await apiGet(`/api/sessions/${sessionId}`);
        if (currentSession?.id === sessionId) {
            currentSession = refreshed;
            renderIdleTranscript();
        }
        updateSessionSummary(refreshed);
    } catch (error) {
        // Leave the last known state in place; the recording is still safe on disk.
    }
}

async function startLive() {
    if (live || !currentSession) return;
    if (!window.isSecureContext || !navigator.mediaDevices?.getUserMedia) {
        liveStatus.textContent = "Microphone access requires HTTPS or localhost.";
        return;
    }
    const s = {sessionId: currentSession.id};
    live = s;
    liveStart.disabled = true;
    liveLanguage.disabled = true;
    liveStatus.textContent = "Connecting...";
    setRecordingLock(true);
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
            encodeURIComponent(liveLanguage.value) + "&session_id=" +
            encodeURIComponent(s.sessionId)
        );
        await new Promise((resolve, reject) => {
            s.timeout = setTimeout(() => reject(new Error("Connection timed out.")), 10000);
            s.socket.onopen = resolve;
            s.socket.onerror = () => reject(new Error("Could not connect to transcription server."));
            s.socket.onclose = () => reject(new Error("Connection closed."));
        });
        clearTimeout(s.timeout);
        s.socket.onmessage = async event => {
            if (live !== s) return;
            const result = JSON.parse(event.data);
            if (result.type === "error") {
                await fail(s, result.message);
                return;
            }
            renderTranscript(result.text, result.partial);
            if (result.type === "done") {
                currentSession.text = joinText(currentSession.text, result.text);
                currentSession.updated_at = new Date().toISOString();
                updateSessionSummary(currentSession);
                await fail(s, "Stopped.", {resync: false});
            }
        };
        s.socket.onclose = () => fail(s, "Connection lost. Restart to continue.");
        s.socket.onerror = () => fail(s, "Transcription connection failed.");
        s.source = s.context.createMediaStreamSource(s.stream);
        s.node = new AudioWorkletNode(s.context, "pcm-capture");
        s.node.port.onmessage = event => {
            if (live !== s || s.socket.readyState !== WebSocket.OPEN) return;
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
    if (!live?.node) return;
    liveStop.disabled = true;
    liveStatus.textContent = "Finishing transcription...";
    live.node.port.postMessage("stop");
}

newSessionButton.addEventListener("click", createSession);
liveStart.addEventListener("click", startLive);
liveStop.addEventListener("click", stopLive);

loadSessions();
