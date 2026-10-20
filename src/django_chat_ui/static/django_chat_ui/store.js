/**
 * One conversation's state, kept up to date from the protocol's events:
 * the conversation, its messages in order, who is typing and who read what.
 * Dispatches "change" after every event that changed something.
 */

function byTime(a, b) {
    return a.createdAt < b.createdAt ? -1 : a.createdAt > b.createdAt ? 1 : 0;
}

/** Merge a partial conversation: capabilities by key (a capability's value
 * itself is replaced), the rest field by field. */
function mergeConversation(current, changes) {
    const merged = { ...current, ...changes };
    if (changes.capabilities) {
        merged.capabilities = {
            ...current.capabilities,
            ...changes.capabilities,
        };
    }
    return merged;
}

export class ConversationStore extends EventTarget {
    constructor(id) {
        super();
        this.id = id;
        this.conversation = { id };
        /** Messages in display order. */
        this.messages = [];
        /** Participant ids typing now. */
        this.typing = new Set();
        /** Participant id → id of the last message they read. */
        this.readUntil = new Map();
        /** Whether older messages can be fetched (section 9). */
        this.more = true;
        this.before = null;
    }

    /** The latest message: the last one loaded, or the conversation's. */
    get lastMessage() {
        return this.messages.at(-1) ?? this.conversation.lastMessage ?? null;
    }

    get participants() {
        return new Map(
            (this.conversation.participants ?? []).map((participant) => [
                participant.id,
                participant,
            ]),
        );
    }

    find(id) {
        return this.messages.find((message) => message.id === id) ?? null;
    }

    findByClientId(clientId) {
        return (
            this.messages.find((message) => message.clientId === clientId) ??
            null
        );
    }

    /** The client's own message, shown before the server confirms it. */
    addPending(message) {
        this.messages.push({ ...message, status: "sending" });
        this.changed();
    }

    /** A message the server didn't take (7.4). */
    fail(clientId, error) {
        const message = this.findByClientId(clientId);
        if (message) {
            Object.assign(message, { status: "failed", error });
            this.changed();
        }
    }

    /** Apply one event frame; `true` if it changed this conversation. */
    apply(frame) {
        const handler = HANDLERS[frame.type];
        if (!handler || !handler.call(this, frame.data ?? {})) {
            return false;
        }
        this.changed();
        return true;
    }

    changed() {
        this.dispatchEvent(new Event("change"));
    }

    insert(message) {
        const own = message.clientId && this.findByClientId(message.clientId);
        if (own) {
            // The server's copy of an optimistic message: same place.
            Object.assign(own, message);
            delete own.error;
            return;
        }
        if (this.find(message.id)) {
            return; // Already there (an event replayed on resume).
        }
        this.messages.push(message);
        this.messages.sort(byTime);
    }
}

/** What each event does to a conversation; `true` if it applied. */
const HANDLERS = {
    "conversation.created"(data) {
        if (data.id !== this.id) return false;
        this.conversation = mergeConversation(this.conversation, data);
        return true;
    },
    "conversation.updated"(data) {
        if (data.id !== this.id) return false;
        this.conversation = mergeConversation(this.conversation, data);
        return true;
    },
    "message.created"(data) {
        if (data.conversation !== this.id) return false;
        this.insert({ ...data, parts: [...(data.parts ?? [])] });
        return true;
    },
    "message.updated"(data) {
        if (data.conversation !== this.id) return false;
        const message = this.find(data.id);
        if (!message) return false;
        Object.assign(message, data);
        return true;
    },
    "message.delta"(data) {
        if (data.conversation !== this.id) return false;
        const message = this.find(data.id);
        if (!message) return false;
        const part = message.parts[data.part];
        if (part?.type === "text") {
            part.text += data.text;
        } else if (!part) {
            message.parts[data.part] = { type: "text", text: data.text };
        } else {
            return false; // A delta only extends text.
        }
        return true;
    },
    typing(data) {
        if (data.conversation !== this.id) return false;
        if (data.active) {
            this.typing.add(data.participant);
        } else {
            this.typing.delete(data.participant);
        }
        return true;
    },
    read(data) {
        if (data.conversation !== this.id) return false;
        this.readUntil.set(data.participant, data.until);
        return true;
    },
    history(data) {
        if (data.conversation !== this.id) return false;
        for (const message of data.messages ?? []) {
            this.insert({ ...message, parts: [...(message.parts ?? [])] });
        }
        this.more = Boolean(data.more);
        this.before = data.before ?? null;
        return true;
    },
};
