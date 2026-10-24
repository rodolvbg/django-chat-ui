/**
 * A Matrix client of the Client-Server API (https://spec.matrix.org) — the
 * part of it the components use: `/sync` (long polling, or polling), sending
 * with a local echo, reactions, receipts, typing, older messages, starting a
 * room, uploading files.
 *
 *   const client = new ChatClient({ baseUrl: "/chat", csrfToken });
 *   await client.start();
 *
 * On the same site it uses the site's session (with its CSRF token); any
 * other homeserver, with an access token (`accessToken`).
 */

import { ACTION, CONVERSATION, newTxnId } from "./matrix.js";
import { RoomStore } from "./store.js";

export class MatrixError extends Error {
    constructor(data = {}, status = 0) {
        super(data.error ?? data.errcode ?? `HTTP ${status}`);
        this.errcode = data.errcode ?? "M_UNKNOWN";
        this.status = status;
        this.data = data;
    }
}

const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));

export class ChatClient extends EventTarget {
    /**
     * @param options.baseUrl  the homeserver's ("/chat")
     * @param options.csrfToken  the site's, on the same site
     * @param options.accessToken  a Matrix login's, elsewhere
     * @param options.poll  milliseconds between syncs: polling instead of
     *   long polling (0)
     * @param options.timeout  milliseconds a long poll waits (30000)
     * @param options.retry  milliseconds before syncing again after a
     *   failure (2000)
     * @param options.limit  the messages of each room it starts with
     */
    constructor({
        baseUrl = "",
        csrfToken = "",
        accessToken = "",
        poll = 0,
        timeout = 30000,
        retry = 2000,
        limit = 30,
        fetch = globalThis.fetch?.bind(globalThis),
    } = {}) {
        super();
        this.baseUrl = baseUrl.replace(/\/$/, "");
        this.csrfToken = csrfToken;
        this.accessToken = accessToken;
        this.poll = poll;
        this.timeout = timeout;
        this.retryDelay = retry;
        this.limit = limit;
        this.fetch = fetch;
        this.me = null;
        this.rooms = new Map();
        this.since = null;
        this.running = false;
        this.ready = null;
    }

    // Requests ---------------------------------------------------------------

    async request(method, path, { body, query, raw, signal } = {}) {
        const params = query ? `?${new URLSearchParams(query)}` : "";
        const headers = { Accept: "application/json" };
        if (this.accessToken) {
            headers.Authorization = `Bearer ${this.accessToken}`;
        }
        if (this.csrfToken && method !== "GET") {
            headers["X-CSRFToken"] = this.csrfToken;
        }
        let payload;
        if (raw) {
            headers["Content-Type"] = raw.type || "application/octet-stream";
            payload = raw;
        } else if (body !== undefined) {
            headers["Content-Type"] = "application/json";
            payload = JSON.stringify(body);
        }
        const prefix = path.startsWith("/_matrix") ? "" : "/_matrix/client/v3";
        const response = await this.fetch(
            `${this.baseUrl}${prefix}${path}${params}`,
            {
                method,
                headers,
                body: payload,
                credentials: "same-origin",
                signal,
            },
        );
        const data = await response.json().catch(() => ({}));
        if (!response.ok) throw new MatrixError(data, response.status);
        return data;
    }

    // Syncing ----------------------------------------------------------------

    /** Who it is, then its rooms; resolves once it has them, and keeps them
     * up to date. Commands wait for it: by then the server knows who this
     * client is (a visitor's session is made on its first request). */
    start() {
        if (!this.ready) {
            this.running = true;
            this.ready = (async () => {
                const { user_id } = await this.request(
                    "GET",
                    "/account/whoami",
                );
                this.me = user_id;
                await this.syncOnce(0);
                this.dispatchEvent(new Event("ready"));
                this.loop();
            })();
            this.ready.catch(() => {
                this.ready = null;
                this.running = false;
            });
        }
        return this.ready;
    }

    stop() {
        this.running = false;
        this.ready = null;
        this.abort?.abort();
    }

    async loop() {
        while (this.running) {
            try {
                await this.syncOnce(this.poll ? 0 : this.timeout);
                if (this.poll) await sleep(this.poll);
            } catch {
                if (this.running) await sleep(this.retryDelay);
            }
        }
    }

    async syncOnce(timeout) {
        this.abort = new AbortController();
        const query = {
            timeout: String(timeout),
            filter: JSON.stringify({
                room: { timeline: { limit: this.limit } },
            }),
        };
        if (this.since) query.since = this.since;
        const data = await this.request("GET", "/sync", {
            query,
            signal: this.abort.signal,
        });
        this.applySync(data);
    }

    applySync(data) {
        this.since = data.next_batch;
        let listed = false;
        for (const [id, room] of Object.entries(data.rooms?.join ?? {})) {
            this.room(id).applySync(room);
            listed = true;
        }
        for (const id of Object.keys(data.rooms?.leave ?? {})) {
            const store = this.rooms.get(id);
            if (store) {
                store.joined = false;
                store.left = true;
                store.changed();
                listed = true;
            }
        }
        if (listed) this.dispatchEvent(new Event("conversations"));
        this.dispatchEvent(new CustomEvent("sync", { detail: data }));
    }

    /** The store of a room (made on first use). */
    room(id) {
        if (!this.rooms.has(id)) this.rooms.set(id, new RoomStore(id));
        return this.rooms.get(id);
    }

    /** The rooms it's in, the latest active first. */
    list() {
        const updated = (store) =>
            store.lastMessage?.createdAt ??
            store.stateEvent(CONVERSATION)?.origin_server_ts ??
            0;
        return [...this.rooms.values()]
            .filter((store) => store.joined)
            .sort((a, b) => updated(b) - updated(a));
    }

    // Commands ----------------------------------------------------------------

    async command(method, path, options) {
        await (this.ready ?? this.start());
        return this.request(method, path, options);
    }

    roomPath(room, rest) {
        return `/rooms/${encodeURIComponent(room)}/${rest}`;
    }

    /** Send an event; a message shows at once ("sending"), then as the
     * server has it, or "failed". The same `txnId` is never sent twice.
     * `replyTo`: the event ID of the message it answers. */
    async send(
        room,
        content,
        { type = "m.room.message", txnId, replyTo } = {},
    ) {
        const txn = txnId ?? newTxnId();
        if (replyTo) {
            content = {
                ...content,
                "m.relates_to": { "m.in_reply_to": { event_id: replyTo } },
            };
        }
        const store = this.room(room);
        if (!store.findLocal(txn)) {
            store.addLocal({
                event_id: `~${txn}`,
                txnId: txn,
                type,
                content,
                sender: this.me,
                origin_server_ts: Date.now(),
            });
        }
        try {
            const { event_id } = await this.command(
                "PUT",
                this.roomPath(room, `send/${encodeURIComponent(type)}/${txn}`),
                { body: content },
            );
            store.confirm(txn, event_id);
            return event_id;
        } catch (error) {
            store.fail(txn, error);
            throw error;
        }
    }

    /** Send a failed message again (same transaction: never sent twice). */
    retry(room, txnId) {
        const local = this.room(room).findLocal(txnId);
        if (!local)
            return Promise.reject(new MatrixError({ errcode: "M_NOT_FOUND" }));
        local.local = "sending";
        this.room(room).changed();
        return this.send(room, local.content, { type: local.type, txnId });
    }

    /** Use a button of a message: its label is the answer. */
    action(room, message, button) {
        return this.send(room, {
            msgtype: "m.text",
            body: button.label ?? button.id,
            [ACTION]: { event_id: message, button: button.id },
            "m.relates_to": { "m.in_reply_to": { event_id: message } },
        });
    }

    /** React to a message with `key`. */
    react(room, message, key) {
        return this.send(
            room,
            {
                "m.relates_to": {
                    rel_type: "m.annotation",
                    event_id: message,
                    key,
                },
            },
            { type: "m.reaction" },
        );
    }

    /** Take a reaction back: its event redacted. */
    async unreact(room, message, key) {
        const mine = this.room(room)
            .messages.find((m) => m.id === message)
            ?.reactions.find((r) => r.key === key)
            ?.events.filter((e) => e.sender === this.me && !e.local);
        for (const event of mine ?? []) await this.redact(room, event.event_id);
    }

    redact(room, event, reason) {
        return this.command(
            "PUT",
            this.roomPath(
                room,
                `redact/${encodeURIComponent(event)}/${newTxnId()}`,
            ),
            { body: reason ? { reason } : {} },
        );
    }

    /** Everything up to `event` read. */
    read(room, event) {
        return this.command(
            "POST",
            this.roomPath(room, `receipt/m.read/${encodeURIComponent(event)}`),
            { body: {} },
        );
    }

    typing(room, active) {
        return this.command(
            "PUT",
            this.roomPath(room, `typing/${encodeURIComponent(this.me)}`),
            {
                body: active
                    ? { typing: true, timeout: 30000 }
                    : { typing: false },
            },
        );
    }

    /** Older messages of a room. */
    async history(room, limit = 30) {
        const store = this.room(room);
        if (!store.more) return;
        const data = await this.command(
            "GET",
            this.roomPath(room, "messages"),
            {
                query: {
                    dir: "b",
                    limit: String(limit),
                    from: store.prevBatch,
                },
            },
        );
        store.prepend(data.chunk, data.end);
    }

    /** Start a room with `invite` (user IDs; none: the support team, as the
     * "contact us" widget does); resolves with its ID. */
    async createRoom({ invite = [], channel } = {}) {
        const initial = channel
            ? [{ type: CONVERSATION, state_key: "", content: { channel } }]
            : [];
        const { room_id } = await this.command("POST", "/createRoom", {
            body: { invite, preset: "private_chat", initial_state: initial },
        });
        return room_id;
    }

    /** Upload a file: its `mxc://` URI. */
    async upload(file) {
        const { content_uri } = await this.command(
            "POST",
            "/_matrix/media/v3/upload",
            { raw: file, query: { filename: file.name ?? "file" } },
        );
        return content_uri;
    }

    /** Where an `mxc://` URI is downloaded from (others pass as they are). */
    mediaUrl(uri) {
        const match = /^mxc:\/\/([^/]+)\/([\w-]+)$/.exec(uri ?? "");
        if (!match) return uri;
        return `${this.baseUrl}/_matrix/client/v1/media/download/${match[1]}/${match[2]}`;
    }
}
