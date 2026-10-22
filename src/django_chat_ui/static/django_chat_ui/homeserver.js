/**
 * A Matrix homeserver in memory, scriptable — the part of the
 * Client-Server API the components use: for tests, demos, and building an
 * interface before its backend. Give its `fetch` to a ChatClient:
 *
 *   const server = new FakeHomeserver({ me: { id: "@me:demo", name: "Me" } });
 *   server.addRoom({ id: "!bot:demo", members: [server.me.id, "@bot:demo"] });
 *   server.onMessage = (event, server) => server.post(...);
 *   const client = new ChatClient({ fetch: server.fetch });
 */

import { renderMarkdown } from "./content.js";
import {
    ACTION,
    BUTTONS,
    CAPABILITIES,
    CONVERSATION,
    HTML,
    PARTICIPANT,
    STREAM,
} from "./matrix.js";

const later = () => new Promise((resolve) => setTimeout(resolve, 0));

function json(data, status = 200) {
    return {
        ok: status < 400,
        status,
        json: async () => structuredClone(data),
    };
}

function error(errcode, status = 400, message = errcode) {
    return json({ errcode, error: message }, status);
}

export class FakeHomeserver {
    /**
     * @param options.me  the user the client is: `{ id, name, kind }`
     */
    constructor({ me = { id: "@me:demo", name: "Me" } } = {}) {
        this.me = me;
        this.users = new Map([[me.id, me]]);
        this.rooms = new Map();
        this.log = []; // { pos, room, kind, event? , ephemeral? }
        this.pos = 0;
        this.ids = 0;
        this.waiting = new Set();
        this.received = []; // every request, for tests
        /** Called with (event, server) after the client sends a message. */
        this.onMessage = null;
        /** Called with (event, server, button) when a button is used. */
        this.onAction = null;
        /** Called with (room, server) for a room the client starts. */
        this.onStart = null;
        /** Return `{ errcode, error }` to refuse what the client sends. */
        this.reject = null;
        /** The capabilities of the rooms the client starts. */
        this.newRoom = { capabilities: { composer: { mode: "free" } } };
        this.fetch = (url, init) => this.handle(url, init);
    }

    addUser(user) {
        this.users.set(user.id, user);
        return user;
    }

    // The log ---------------------------------------------------------------

    record(room, entry) {
        this.pos += 1;
        this.log.push({ pos: this.pos, room, ...entry });
        for (const wake of this.waiting) wake();
    }

    event(room, sender, type, content, extra = {}) {
        this.ids += 1;
        const event = {
            type,
            content,
            sender,
            event_id: `$${this.ids}`,
            origin_server_ts: extra.ts ?? Date.now(),
            ...(extra.state_key !== undefined
                ? { state_key: extra.state_key }
                : {}),
            ...(extra.unsigned ? { unsigned: extra.unsigned } : {}),
        };
        const data = this.rooms.get(room);
        data.events.push(event);
        if (event.state_key !== undefined) {
            data.state.set(`${type}\u0000${event.state_key}`, event);
        }
        this.record(room, { kind: "event", event });
        return event;
    }

    ephemeral(room, type, content) {
        this.record(room, { kind: "ephemeral", ephemeral: { type, content } });
    }

    // Scripting -------------------------------------------------------------

    /** A room: its members (user IDs, added as users if unknown), title,
     * channel, state and capabilities; and its messages (`{ sender,
     * content, ts? }`). */
    addRoom(
        {
            id,
            members = [this.me.id],
            title,
            channel = "web",
            state = "open",
            capabilities = {},
            unread = 0,
        },
        messages = [],
    ) {
        this.rooms.set(id, {
            id,
            events: [],
            state: new Map(),
            receipts: {},
            typing: new Set(),
            unread,
            members: new Set(),
        });
        this.event(
            id,
            this.me.id,
            "m.room.create",
            { room_version: "11" },
            {
                state_key: "",
            },
        );
        for (const member of members) this.join(id, member);
        if (title) {
            this.event(
                id,
                this.me.id,
                "m.room.name",
                { name: title },
                {
                    state_key: "",
                },
            );
        }
        this.event(
            id,
            this.me.id,
            CONVERSATION,
            { channel, state },
            {
                state_key: "",
            },
        );
        this.event(id, this.me.id, CAPABILITIES, capabilities, {
            state_key: "",
        });
        for (const message of messages) {
            this.event(id, message.sender, "m.room.message", message.content, {
                ts: message.ts,
                unsigned: message.unsigned,
            });
        }
        this.rooms.get(id).unread = unread;
        return this.rooms.get(id);
    }

    join(room, member) {
        const user = this.users.get(member) ?? this.addUser({ id: member });
        this.rooms.get(room).members.add(member);
        const content = {
            membership: "join",
            [PARTICIPANT]: { kind: user.kind ?? "user", handle: user.handle },
        };
        if (user.name) content.displayname = user.name;
        this.event(room, member, "m.room.member", content, {
            state_key: member,
        });
    }

    /** `member` leaves the room (the client, if it's them: it's gone). */
    leave(room, member) {
        this.rooms.get(room).members.delete(member);
        this.event(
            room,
            member,
            "m.room.member",
            { membership: "leave" },
            {
                state_key: member,
            },
        );
        if (member === this.me.id) this.record(room, { kind: "leave" });
    }

    /** A message of `sender`: the client's unread count goes up. */
    post(room, sender, content, extra) {
        const event = this.event(
            room,
            sender,
            "m.room.message",
            content,
            extra,
        );
        if (sender !== this.me.id) {
            this.rooms.get(room).unread += 1;
            this.record(room, { kind: "unread" });
        }
        return event;
    }

    /** A message written a little at a time (`chunks`, markdown), then
     * sent, with its HTML, as a server does. */
    async stream(room, sender, chunks, final = {}) {
        const id = `s${this.ids + 1}`;
        let body = "";
        for (const chunk of chunks) {
            body += chunk;
            await later();
            this.ephemeral(room, STREAM, { id, sender, body, markdown: true });
        }
        await later();
        const html = renderMarkdown(body);
        return this.post(room, sender, {
            msgtype: "m.text",
            body: html.textContent,
            format: HTML,
            formatted_body: html.innerHTML,
            ...final,
            [STREAM]: { id },
        });
    }

    /** Change what a room allows (the whole capabilities, merged by key). */
    setCapabilities(room, capabilities) {
        const current = this.rooms
            .get(room)
            .state.get(`${CAPABILITIES}\u0000`).content;
        this.event(
            room,
            this.me.id,
            CAPABILITIES,
            { ...current, ...capabilities },
            {
                state_key: "",
            },
        );
    }

    typing(room, user, active) {
        const typing = this.rooms.get(room).typing;
        if (active) typing.add(user);
        else typing.delete(user);
        this.ephemeral(room, "m.typing", { user_ids: [...typing] });
    }

    receipt(room, user, event, type = "m.read") {
        this.rooms.get(room).receipts[user] = { [type]: event };
        this.ephemeral(room, "m.receipt", {
            [event]: { [type]: { [user]: { ts: Date.now() } } },
        });
    }

    redact(room, eventId, sender = this.me.id) {
        const target = this.rooms
            .get(room)
            .events.find((event) => event.event_id === eventId);
        const redaction = this.event(room, sender, "m.room.redaction", {
            redacts: eventId,
        });
        target.content = {};
        target.unsigned = { ...target.unsigned, redacted_because: redaction };
        return redaction;
    }

    // Sync -------------------------------------------------------------------

    /** A room as a client with nothing of it gets it: its latest
     * `limit` events, the state before them. */
    roomView(room, limit) {
        const start = Math.max(0, room.events.length - limit);
        const timeline = room.events.slice(start);
        const view = {
            state: {
                events: [...room.state.values()].filter(
                    (event) => !timeline.includes(event),
                ),
            },
            timeline: { events: timeline, limited: start > 0 },
            ephemeral: {
                events: [
                    {
                        type: "m.typing",
                        content: { user_ids: [...room.typing] },
                    },
                    { type: "m.receipt", content: this.receiptContent(room) },
                ],
            },
            unread_notifications: { notification_count: room.unread },
        };
        if (start > 0) view.timeline.prev_batch = `t${start}`;
        return view;
    }

    receiptContent(room) {
        const content = {};
        for (const [user, kinds] of Object.entries(room.receipts)) {
            for (const [kind, event] of Object.entries(kinds)) {
                content[event] ??= {};
                content[event][kind] ??= {};
                content[event][kind][user] = { ts: 0 };
            }
        }
        return content;
    }

    syncResponse(since, limit = 30) {
        const rooms = { join: {}, leave: {}, invite: {} };
        if (since === null) {
            for (const room of this.rooms.values()) {
                rooms.join[room.id] = this.roomView(room, limit);
            }
            return { next_batch: `s${this.pos}`, rooms };
        }
        const entries = this.log.filter((entry) => entry.pos > since);
        const joined = new Set(
            entries.filter((e) => e.kind === "join").map((e) => e.room),
        );
        for (const id of joined) {
            rooms.join[id] = this.roomView(this.rooms.get(id), limit);
        }
        for (const entry of entries) {
            if (joined.has(entry.room)) continue;
            if (entry.kind === "leave") {
                rooms.leave[entry.room] = { timeline: { events: [] } };
                continue;
            }
            rooms.join[entry.room] ??= {
                timeline: { events: [], limited: false },
                ephemeral: { events: [] },
            };
            const room = rooms.join[entry.room];
            if (entry.kind === "event") room.timeline.events.push(entry.event);
            if (entry.kind === "ephemeral") {
                room.ephemeral.events.push(entry.ephemeral);
            }
            room.unread_notifications = {
                notification_count: this.rooms.get(entry.room).unread,
            };
        }
        return { next_batch: `s${this.pos}`, rooms };
    }

    async sync(query) {
        const since = query.get("since");
        const after = since ? Number(since.slice(1)) : null;
        const timeout = Number(query.get("timeout") ?? 0);
        if (after !== null && after >= this.pos && timeout > 0) {
            await new Promise((resolve) => {
                const wake = () => {
                    this.waiting.delete(wake);
                    clearTimeout(timer);
                    resolve();
                };
                const timer = setTimeout(wake, timeout);
                this.waiting.add(wake);
            });
        }
        let limit = 30;
        try {
            limit = JSON.parse(query.get("filter")).room.timeline.limit;
        } catch {
            // No filter: 30.
        }
        return json(this.syncResponse(after, limit));
    }

    // Requests -------------------------------------------------------------

    async handle(url, init = {}) {
        await later(); // Asynchronous, as over a network.
        const parsed = new URL(url, "http://fake.invalid");
        const method = init.method ?? "GET";
        const path = decodeURIComponent(parsed.pathname).replace(
            /^.*?\/_matrix\//,
            "/_matrix/",
        );
        const body =
            typeof init.body === "string" ? JSON.parse(init.body) : init.body;
        this.received.push({ method, path, body, query: parsed.searchParams });
        const client = "/_matrix/client/v3";
        if (path === `${client}/account/whoami`) {
            return json({ user_id: this.me.id });
        }
        if (path === `${client}/sync`) return this.sync(parsed.searchParams);
        if (path === `${client}/createRoom`) return this.createRoom(body);
        if (path === "/_matrix/media/v3/upload") {
            this.ids += 1;
            return json({ content_uri: `mxc://demo/m${this.ids}` });
        }
        const match = /^\/_matrix\/client\/v3\/rooms\/([^/]+)\/(.+)$/.exec(
            path,
        );
        const room = match && this.rooms.get(match[1]);
        if (!room) return error("M_FORBIDDEN", 403);
        const [action, ...rest] = match[2].split("/");
        const handler = ROOM[action];
        if (!handler) return error("M_UNRECOGNIZED", 404);
        return handler.call(this, room, rest, body, parsed.searchParams);
    }

    createRoom(body) {
        const id = `!r${this.rooms.size + 1}:demo`;
        const channel = body?.initial_state?.find(
            (state) => state.type === CONVERSATION,
        )?.content?.channel;
        this.addRoom({
            id,
            members: [this.me.id, ...(body?.invite ?? [])],
            channel: channel ?? "web",
            state: "pending",
            ...this.newRoom,
        });
        this.record(id, { kind: "join" });
        this.onStart?.(id, this);
        return json({ room_id: id });
    }
}

/** What each request to a room does. */
const ROOM = {
    send(room, [type, txn], body) {
        const sent = room.events.find(
            (e) => e.sender === this.me.id && e.txn === txn,
        );
        if (sent) return json({ event_id: sent.event_id });
        const refused = this.reject?.({ type, content: body }, this);
        if (refused) return json(refused, 400);
        const capabilities = room.state.get(`${CAPABILITIES}\u0000`).content;
        if (type === "m.reaction" && !capabilities.reactions) {
            return error("IO.GITHUB.RODOLVBG.CHAT.UNSUPPORTED", 403);
        }
        const event = this.event(room.id, this.me.id, type, body, {
            unsigned: { transaction_id: txn },
        });
        event.txn = txn;
        const action = body?.[ACTION];
        if (action) {
            const message = room.events.find(
                (e) => e.event_id === action.event_id,
            );
            const button = message?.content[BUTTONS]?.buttons.find(
                (b) => b.id === action.button,
            );
            this.onAction?.(event, this, button);
        } else if (type === "m.room.message") {
            this.onMessage?.(event, this);
        }
        return json({ event_id: event.event_id });
    },
    redact(room, [event]) {
        if (!room.events.some((e) => e.event_id === event)) {
            return error("M_NOT_FOUND", 404);
        }
        const redaction = this.redact(room.id, event);
        return json({ event_id: redaction.event_id });
    },
    receipt(room, [type, event]) {
        room.unread = 0;
        this.receipt(room.id, this.me.id, event, type);
        this.record(room.id, { kind: "unread" });
        return json({});
    },
    typing(room, _rest, body) {
        this.typing(room.id, this.me.id, Boolean(body?.typing));
        return json({});
    },
    messages(room, _rest, _body, query) {
        const before = query.get("from");
        const limit = Number(query.get("limit") ?? 10);
        const end = before ? Number(before.slice(1)) : room.events.length;
        const start = Math.max(0, end - limit);
        const chunk = room.events.slice(start, end).reverse();
        return json({
            chunk,
            start: before,
            ...(start > 0 ? { end: `t${start}` } : {}),
        });
    },
};
