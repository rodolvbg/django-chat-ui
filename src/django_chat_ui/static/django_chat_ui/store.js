/**
 * One room's state, kept up to date from `/sync`: its state events, its
 * timeline (with the client's own events not yet confirmed), its receipts,
 * who is typing and the messages being written. Dispatches "change" after
 * everything that changed something.
 *
 * What the components read of it — `conversation` and `messages` — is
 * derived from the events: edits applied, reactions gathered, statuses
 * from receipts.
 */

import {
    ACTION,
    CAPABILITIES,
    CONVERSATION,
    DELIVERED,
    PARTICIPANT,
    STATUS,
    STREAM,
} from "./matrix.js";

export class RoomStore extends EventTarget {
    constructor(id) {
        super();
        this.id = id;
        /** type → state key → event */
        this.state = new Map();
        /** Events in order, the client's pending ones last. */
        this.events = [];
        /** user ID → receipt type → event ID */
        this.receipts = new Map();
        /** User IDs typing now. */
        this.typing = new Set();
        /** Messages being written: stream id → its content. */
        this.streams = new Map();
        /** Those written already (their message came). */
        this.written = new Set();
        /** event ID → { status, error } (this package's `status`). */
        this.statuses = new Map();
        this.unread = 0;
        /** Where older events start (`/messages`), and whether there are. */
        this.prevBatch = null;
        this.more = false;
        this.joined = false;
        this.cache = null;
    }

    changed() {
        this.cache = null;
        this.dispatchEvent(new Event("change"));
    }

    stateEvent(type, key = "") {
        return this.state.get(type)?.get(key) ?? null;
    }

    stateContent(type, key = "") {
        return this.stateEvent(type, key)?.content ?? null;
    }

    find(id) {
        return this.events.find((event) => event.event_id === id) ?? null;
    }

    // From the server ---------------------------------------------------------

    /** Apply a room of `/sync` (`initial`: the first one, or `limited`). */
    applySync(room) {
        if (room.timeline?.limited) {
            // A gap: what's loaded can't be joined to what comes.
            this.events = this.events.filter((event) => event.local);
            this.prevBatch = room.timeline.prev_batch ?? null;
            this.more = Boolean(this.prevBatch);
        } else if (!this.joined) {
            this.prevBatch = room.timeline?.prev_batch ?? null;
            this.more = Boolean(this.prevBatch);
        }
        this.joined = true;
        for (const event of room.state?.events ?? []) this.setState(event);
        for (const event of room.timeline?.events ?? []) this.addEvent(event);
        for (const event of room.ephemeral?.events ?? []) {
            this.applyEphemeral(event);
        }
        const count = room.unread_notifications?.notification_count;
        if (typeof count === "number") this.unread = count;
        this.changed();
    }

    setState(event) {
        if (typeof event.state_key !== "string") return;
        if (!this.state.has(event.type)) this.state.set(event.type, new Map());
        this.state.get(event.type).set(event.state_key, event);
    }

    addEvent(event) {
        if (this.find(event.event_id)) return; // Already there (replayed).
        const txn = event.unsigned?.transaction_id;
        const index = this.events.findIndex(
            (local) =>
                local.local &&
                (local.confirmed === event.event_id ||
                    (txn && local.txnId === txn)),
        );
        if (index >= 0) this.events.splice(index, 1);
        // Before the client's pending ones: the server's order.
        const at = this.events.findIndex((other) => other.local);
        if (at >= 0) this.events.splice(at, 0, event);
        else this.events.push(event);
        if (typeof event.state_key === "string") this.setState(event);
        if (event.type === "m.room.redaction") {
            this.redact(event.content?.redacts ?? event.redacts, event);
        }
        const stream = event.content?.[STREAM]?.id;
        if (stream) {
            this.streams.delete(stream);
            this.written.add(stream);
        }
        if (event.type === "m.room.message") this.typing.delete(event.sender);
    }

    redact(id, because) {
        const target = this.find(id);
        if (!target) return;
        target.content = {};
        target.unsigned = { ...target.unsigned, redacted_because: because };
    }

    applyEphemeral(event) {
        const content = event.content ?? {};
        if (event.type === "m.typing") {
            this.typing = new Set(content.user_ids ?? []);
        } else if (event.type === "m.receipt") {
            for (const [id, kinds] of Object.entries(content)) {
                for (const [kind, users] of Object.entries(kinds)) {
                    for (const user of Object.keys(users)) {
                        if (!this.receipts.has(user)) {
                            this.receipts.set(user, {});
                        }
                        this.receipts.get(user)[kind] = id;
                    }
                }
            }
        } else if (event.type === STREAM) {
            // Its message may have come first, in the same sync.
            if (content.done || this.written.has(content.id)) {
                this.streams.delete(content.id);
            } else {
                this.streams.set(content.id, content);
            }
        } else if (event.type === STATUS) {
            this.statuses.set(content.event_id, content);
        }
    }

    /** Older events, from `/messages` (newest first). */
    prepend(chunk, end) {
        const known = new Set(this.events.map((event) => event.event_id));
        const older = chunk.filter((event) => !known.has(event.event_id));
        older.reverse();
        this.events.unshift(...older);
        for (const event of older) {
            if (event.type === "m.room.redaction") {
                this.redact(event.content?.redacts ?? event.redacts, event);
            }
        }
        this.prevBatch = end ?? null;
        this.more = Boolean(end);
        this.changed();
    }

    // The client's own --------------------------------------------------------

    /** An event of the client's, shown before the server has it. */
    addLocal(event) {
        this.events.push({ ...event, local: "sending" });
        this.changed();
    }

    findLocal(txnId) {
        return this.events.find((event) => event.txnId === txnId) ?? null;
    }

    /** The server took it: its ID, until `/sync` brings it. */
    confirm(txnId, eventId) {
        const local = this.findLocal(txnId);
        if (!local) return;
        if (this.find(eventId)) {
            this.events.splice(this.events.indexOf(local), 1);
        } else {
            Object.assign(local, { local: "sent", confirmed: eventId });
        }
        this.changed();
    }

    fail(txnId, error) {
        const local = this.findLocal(txnId);
        if (local) {
            Object.assign(local, { local: "failed", error });
            this.changed();
        }
    }

    // What the components read ------------------------------------------------

    /** Its participants: user ID → { id, name, kind, handle, avatar, ext }. */
    get participants() {
        const members = new Map();
        for (const [key, event] of this.state.get("m.room.member") ?? []) {
            const content = event.content;
            if (content.membership !== "join") continue;
            const own = content[PARTICIPANT] ?? {};
            members.set(key, {
                id: key,
                name: content.displayname ?? "",
                kind: own.kind ?? "user",
                handle: own.handle,
                avatar: own.avatar,
                ext: own.ext,
            });
        }
        return members;
    }

    /** The conversation: its title, channel, state, capabilities, unread. */
    get conversation() {
        const own = this.stateContent(CONVERSATION) ?? {};
        return {
            id: this.id,
            title: this.stateContent("m.room.name")?.name || undefined,
            channel: own.channel,
            state: own.state,
            ext: own.ext,
            capabilities: this.stateContent(CAPABILITIES) ?? {},
            participants: [...this.participants.values()],
            unread: this.unread,
        };
    }

    /** Its messages in order, as they are now; the ones being written last. */
    get messages() {
        if (!this.cache) this.cache = this.build();
        return this.cache;
    }

    get lastMessage() {
        return this.messages.at(-1) ?? null;
    }

    build() {
        const edits = new Map();
        const reactions = new Map();
        const answered = new Set();
        const position = new Map();
        this.events.forEach((event, index) => {
            position.set(event.event_id, index);
            const relation = event.content?.["m.relates_to"];
            if (event.type === "m.reaction" && !redacted(event)) {
                const key = relation?.key;
                if (relation?.rel_type !== "m.annotation" || !key) return;
                const of = reactions.get(relation.event_id) ?? new Map();
                const by = of.get(key) ?? [];
                by.push(event);
                of.set(key, by);
                reactions.set(relation.event_id, of);
            } else if (
                event.type === "m.room.message" &&
                relation?.rel_type === "m.replace"
            ) {
                edits.set(relation.event_id, event);
            }
            const action = event.content?.[ACTION];
            if (action?.event_id) answered.add(action.event_id);
        });
        const read = this.readPositions(position);
        const messages = [];
        for (const event of this.events) {
            if (event.type !== "m.room.message") continue;
            const relation = event.content?.["m.relates_to"];
            if (relation?.rel_type === "m.replace") continue;
            const edit = edits.get(event.event_id);
            const replaced =
                edit &&
                edit.sender === event.sender &&
                edit.content?.["m.new_content"];
            const index = position.get(event.event_id);
            messages.push({
                id: event.event_id,
                txnId: event.txnId ?? event.unsigned?.transaction_id,
                sender: event.sender,
                content: replaced || event.content,
                createdAt: event.origin_server_ts,
                edited: Boolean(replaced),
                redacted: redacted(event),
                replyTo: relation?.["m.in_reply_to"]?.event_id,
                used: answered.has(event.event_id),
                reactions: [
                    ...(reactions.get(event.event_id) ?? new Map()),
                ].map(([key, events]) => ({
                    key,
                    by: events.map((e) => e.sender),
                    events,
                })),
                ...this.status(event, index, read),
            });
        }
        for (const stream of this.streams.values()) {
            messages.push({
                id: `stream:${stream.id}`,
                sender: stream.sender,
                content: {
                    msgtype: "m.text",
                    body: stream.body,
                    markdown: Boolean(stream.markdown),
                },
                streaming: true,
                reactions: [],
            });
        }
        return messages;
    }

    /** Where each user's receipts are: user → type → position. */
    readPositions(position) {
        const reached = new Map();
        for (const [user, kinds] of this.receipts) {
            const at = {};
            for (const [kind, id] of Object.entries(kinds)) {
                if (position.has(id)) at[kind] = position.get(id);
            }
            reached.set(user, at);
        }
        return reached;
    }

    /** A message's status: the client's own pending ones', a failure, or
     * how far the others' receipts got. */
    status(event, index, read) {
        if (event.local === "sending" || event.local === "failed") {
            return { status: event.local, error: event.error };
        }
        const own =
            this.statuses.get(event.event_id) ?? event.unsigned?.[STATUS];
        if (own?.status === "failed") {
            return { status: "failed", error: own.error };
        }
        let status = "sent";
        for (const [user, at] of read) {
            if (user === event.sender) continue;
            if (index <= (at["m.read"] ?? -1)) return { status: "read" };
            if (index <= (at[DELIVERED] ?? -1)) status = "delivered";
        }
        return { status };
    }
}

function redacted(event) {
    return Boolean(event.unsigned?.redacted_because);
}
