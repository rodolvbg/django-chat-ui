/**
 * The protocol over a WebSocket (docs/protocol.md, 10.2): one frame per
 * message, both ways. It reconnects by itself, saying hello again with what
 * it last got, so the server resumes from there.
 *
 *   new WebSocketTransport({ url: "/chat/ws" })
 */

export class WebSocketTransport {
    constructor({ url, retry = 1000, WebSocket = globalThis.WebSocket }) {
        this.url = absolute(url);
        this.retry = retry;
        this.WebSocket = WebSocket;
        this.onFrame = null;
        this.socket = null;
        this.hello = null;
        this.seq = null;
        this.closed = true;
        this.reconnects = 0;
    }

    connect(onFrame, { resume } = {}) {
        this.close();
        this.onFrame = onFrame;
        this.seq = resume?.seq ?? this.seq;
        this.closed = false;
        return this.open();
    }

    open() {
        return new Promise((resolve, reject) => {
            const socket = new this.WebSocket(this.url);
            this.socket = socket;
            let opened = false;
            socket.onopen = () => {
                opened = true;
                resolve();
            };
            socket.onmessage = (event) => this.receive(event.data);
            socket.onclose = () => {
                if (!opened) {
                    reject(new Error("The chat's WebSocket can't be opened."));
                } else if (!this.closed && socket === this.socket) {
                    setTimeout(() => this.reopen(), this.retry);
                }
            };
        });
    }

    async reopen() {
        if (this.closed) return;
        try {
            await this.open();
        } catch {
            setTimeout(() => this.reopen(), this.retry);
            return;
        }
        if (!this.hello) return;
        // Hello again, from the last event it got (8.3).
        this.reconnects += 1;
        const { resume, ...data } = this.hello.data ?? {};
        this.socket.send(
            JSON.stringify({
                ...this.hello,
                id: `${this.hello.id}-${this.reconnects}`,
                data:
                    this.seq === null
                        ? data
                        : { ...data, resume: { seq: this.seq } },
            }),
        );
    }

    receive(text) {
        let frame;
        try {
            frame = JSON.parse(text);
        } catch {
            return; // Not a frame: ignored (must-ignore, 3.1).
        }
        if (typeof frame.seq === "number") this.seq = frame.seq;
        this.onFrame?.(frame);
    }

    async send(frame) {
        if (frame.type === "hello") this.hello = frame;
        if (!this.socket || this.socket.readyState !== 1) {
            throw new Error("The chat's WebSocket isn't open.");
        }
        this.socket.send(JSON.stringify(frame));
    }

    close() {
        this.closed = true;
        this.socket?.close();
        this.socket = null;
    }
}

function absolute(url) {
    if (/^wss?:/.test(url)) return url;
    const { protocol, host } = globalThis.location;
    return `${protocol === "https:" ? "wss" : "ws"}://${host}${url}`;
}
