class PCMCapture extends AudioWorkletProcessor {
    constructor() {
        super();
        this.buffer = new ArrayBuffer(8000);
        this.view = new DataView(this.buffer);
        this.count = 0;
        this.stopped = false;
        this.port.onmessage = event => {
            if (event.data === "stop") {
                this.stopped = true;
                this.flush();
                this.port.postMessage("flushed");
            }
        };
    }

    flush() {
        if (this.count) {
            const packet = this.buffer.slice(0, this.count * 2);
            this.port.postMessage(packet, [packet]);
            this.count = 0;
        }
    }

    process(inputs) {
        if (this.stopped) return false;
        const channel = inputs[0]?.[0];
        if (channel) {
            for (const sample of channel) {
                const value = Math.max(-1, Math.min(1, sample));
                this.view.setInt16(this.count * 2,
                    Math.round(value * (value < 0 ? 32768 : 32767)), true);
                if (++this.count === 4000) this.flush();
            }
        }
        return true;
    }
}

registerProcessor("pcm-capture", PCMCapture);
