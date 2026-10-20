/**
 * The protocol over HTTP (docs/protocol.md, section 10): events from a
 * Server-Sent Events stream (or polled), commands POSTed as JSON. The
 * answers to a command come in its response.
 *
 *   new HttpTransport({ events: "/chat/events", commands: "/chat/commands",
 *                       csrfToken })
 *   new HttpTransport({ ..., poll: 3000 })   // polling instead of SSE
 */

export class HttpTransport {
    constructor({
        events,
        commands,
        csrfToken = "",
        poll = 0,
        fetch = globalThis.fetch.bind(globalThis),
        EventSource = globalThis.EventSource,
    }) {
        this.events = events;
        this.commands = commands;
        this.csrfToken = csrfToken;
        this.poll = poll;
        this.fetch = fetch;
        this.EventSource = EventSource;
        this.onFrame = null;
        this.source = null;
        this.timer = null;
        this.seq = null;
    }

    url(after) {
        if (after === null || after === undefined) return this.events;
        const separator = this.events.includes("?") ? "&" : "?";
        return `${this.events}${separator}after=${encodeURIComponent(after)}`;
    }

    /** Resolves once the stream is open: nothing sent after it is missed. */
    connect(onFrame, { resume } = {}) {
        this.close();
        this.onFrame = onFrame;
        this.seq = resume?.seq ?? null;
        return this.poll ? this.startPolling() : this.startStream();
    }

    startStream() {
        return new Promise((resolve, reject) => {
            const source = new this.EventSource(this.url(this.seq));
            this.source = source;
            let opened = false;
            source.onopen = () => {
                opened = true;
                resolve();
            };
            source.onmessage = (event) => this.receive(event.data);
            source.onerror = () => {
                // It reconnects by itself (with its Last-Event-ID); only a
                // stream that never opened fails.
                if (!opened && source.readyState === 2) {
                    reject(new Error("The chat's stream can't be opened."));
                }
            };
        });
    }

    async startPolling() {
        await this.pollOnce();
        this.timer = setInterval(() => {
            this.pollOnce().catch(() => {});
        }, this.poll);
    }

    async pollOnce() {
        const response = await this.fetch(this.url(this.seq), {
            headers: { Accept: "application/json" },
            credentials: "same-origin",
        });
        if (!response.ok) throw new Error(`HTTP ${response.status}`);
        const { frames, seq } = await response.json();
        for (const frame of frames) this.onFrame?.(frame);
        this.seq = seq;
    }

    receive(text) {
        let frame;
        try {
            frame = JSON.parse(text);
        } catch {
            return; // Not a frame: ignored (must-ignore, 3.1).
        }
        this.onFrame?.(frame);
    }

    async send(frame) {
        const response = await this.fetch(this.commands, {
            method: "POST",
            credentials: "same-origin",
            headers: {
                "Content-Type": "application/json",
                Accept: "application/json",
                "X-CSRFToken": this.csrfToken,
            },
            body: JSON.stringify(frame),
        });
        let answers = [];
        try {
            answers = await response.json();
        } catch {
            // No frames: below.
        }
        if (!Array.isArray(answers) || !answers.length) {
            throw new Error(`HTTP ${response.status}`);
        }
        for (const answer of answers) this.onFrame?.(answer);
    }

    close() {
        this.source?.close();
        this.source = null;
        clearInterval(this.timer);
        this.timer = null;
    }
}

/** An uploader for <chat-thread>: POSTs the file, answers with its part. */
export function httpUploader({
    uploads,
    csrfToken = "",
    fetch = globalThis.fetch.bind(globalThis),
}) {
    return async (file, conversation) => {
        const body = new FormData();
        body.append("conversation", conversation);
        body.append("file", file);
        const response = await fetch(uploads, {
            method: "POST",
            credentials: "same-origin",
            headers: { "X-CSRFToken": csrfToken },
            body,
        });
        const answer = await response.json().catch(() => ({}));
        if (!response.ok) {
            throw new Error(answer.error?.message ?? `HTTP ${response.status}`);
        }
        return answer;
    };
}
