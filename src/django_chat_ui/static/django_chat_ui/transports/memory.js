/**
 * An in-memory transport and a scriptable fake server that speaks the
 * protocol: for tests, demos, and building an interface before its backend.
 *
 *   const server = new FakeServer({ me: { id: "p_me", kind: "user" } });
 *   server.addConversation({ id: "conv_bot", channel: "bot", ... });
 *   server.onMessage = (message, server) => server.reply(...);
 *   const client = new ChatClient(new MemoryTransport(server));
 */

import { newId } from "../protocol.js";

const later = () => new Promise((resolve) => setTimeout(resolve, 0));

export class MemoryTransport {
    constructor(server) {
        this.server = server;
        this.onFrame = null;
    }

    async connect(onFrame, { resume } = {}) {
        this.onFrame = onFrame;
        this.server.attach(this, resume);
    }

    async send(frame) {
        // Asynchronous, as over a network.
        await later();
        this.server.receive(structuredClone(frame), this);
    }

    deliver(frame) {
        this.onFrame?.(structuredClone(frame));
    }

    close() {
        this.server.detach(this);
        this.onFrame = null;
    }
}

export class FakeServer {
    /**
     * @param options.me  the participant the client is
     * @param options.protocol  the version it answers with
     */
    constructor({ me, protocol = "1.0", capabilities = {} } = {}) {
        this.me = me;
        this.protocol = protocol;
        this.capabilities = capabilities;
        this.conversations = new Map();
        this.messages = new Map(); // conversation id → messages
        this.log = []; // every event sent, for resuming
        this.seq = 0;
        this.transports = new Set();
        this.received = []; // every command received, for tests
        /** Called with (message, server) after a message is sent. */
        this.onMessage = null;
        /** Called with (data, server) on an `action`. */
        this.onAction = null;
        /** Return an Error object to reject a message.send. */
        this.reject = null;
        /** Fields of the conversations clients start (conversation.open
         * with `with`), and a hook called with each. */
        this.newConversation = {};
        this.onStart = null;
    }

    attach(transport, resume) {
        this.transports.add(transport);
        this.resume = resume;
    }

    detach(transport) {
        this.transports.delete(transport);
    }

    addConversation(conversation, messages = []) {
        // Its own copies, as a real server's: updating them changes nothing
        // outside.
        const own = structuredClone(conversation);
        // Its last message, for a list of conversations (as `ready` has it).
        const last = messages.at(-1);
        if (last && !own.lastMessage) own.lastMessage = structuredClone(last);
        this.conversations.set(own.id, own);
        this.messages.set(own.id, structuredClone(messages));
        return own;
    }

    /** Send an event to the clients (with its seq, for resuming). */
    emit(type, data, ref) {
        this.seq += 1;
        const frame = { type, seq: this.seq, data };
        if (ref) frame.ref = ref;
        this.log.push(frame);
        for (const transport of this.transports) transport.deliver(frame);
        return frame;
    }

    /** Answer a command without an event of the stream (no seq). */
    answer(type, data, ref) {
        const frame = { type, ref, data };
        for (const transport of this.transports) transport.deliver(frame);
    }

    receive(frame) {
        this.received.push(frame);
        const handler = COMMANDS[frame.type];
        if (!handler) {
            this.answer(
                "error",
                { code: "unknown_command", message: frame.type },
                frame.id,
            );
            return;
        }
        handler.call(this, frame.data ?? {}, frame);
    }

    /** Add a message to a conversation, as `author`. */
    post(conversation, author, parts, extra = {}) {
        const message = {
            id: newId("m"),
            conversation,
            author,
            parts,
            createdAt: new Date().toISOString(),
            ...extra,
        };
        this.messages.get(conversation)?.push(message);
        this.emit("message.created", message);
        const current = this.conversations.get(conversation);
        if (current) {
            const changes = { lastMessage: message, updatedAt: message.createdAt };
            if (author !== this.me.id) {
                changes.unread = (current.unread ?? 0) + 1;
            }
            Object.assign(current, changes);
            this.emit("conversation.updated", { id: conversation, ...changes });
        }
        return message;
    }

    /** Stream `text` as a new message of `author`, in `chunks`. */
    async stream(conversation, author, chunks, final = {}) {
        const message = this.post(conversation, author, [], {
            streaming: true,
        });
        for (const chunk of chunks) {
            await later();
            this.emit("message.delta", {
                id: message.id,
                conversation,
                part: 0,
                text: chunk,
            });
        }
        await later();
        this.emit("message.updated", {
            id: message.id,
            conversation,
            streaming: false,
            ...final,
        });
        return message;
    }

    update(conversation, changes) {
        const current = this.conversations.get(conversation);
        Object.assign(current, changes);
        this.emit("conversation.updated", { id: conversation, ...changes });
    }
}

const COMMANDS = {
    hello(data, frame) {
        const resumed =
            Boolean(this.resume) && this.resume.seq <= this.seq;
        this.answer(
            "ready",
            {
                protocol: this.protocol,
                me: this.me,
                capabilities: this.capabilities,
                conversations: [...this.conversations.values()],
                resumed,
            },
            frame.id,
        );
        if (resumed) {
            for (const event of this.log.filter(
                (event) => event.seq > this.resume.seq,
            )) {
                for (const transport of this.transports) transport.deliver(event);
            }
        }
    },
    "message.send"(data, frame) {
        const existing = (this.messages.get(data.conversation) ?? []).find(
            (message) => message.clientId === data.clientId,
        );
        if (existing) {
            this.answer("ack", {}, frame.id); // Idempotent (7.3).
            return;
        }
        const error = this.reject?.(data, this);
        if (error) {
            this.answer("error", error, frame.id);
            return;
        }
        this.answer("ack", {}, frame.id);
        const message = this.post(data.conversation, this.me.id, data.parts, {
            clientId: data.clientId,
            status: "sent",
            ...(data.replyTo ? { replyTo: data.replyTo } : {}),
        });
        this.onMessage?.(message, this);
    },
    action(data, frame) {
        this.answer("ack", {}, frame.id);
        this.onAction?.(data, this);
    },
    "message.read"(data, frame) {
        this.answer("ack", {}, frame.id);
        const conversation = this.conversations.get(data.conversation);
        if (conversation?.unread) {
            conversation.unread = 0;
            this.emit("conversation.updated", { id: data.conversation, unread: 0 });
        }
    },
    typing(data, frame) {
        this.answer("ack", {}, frame.id);
    },
    "conversation.open"(data, frame) {
        if (data.with) {
            // A new conversation, as the "contact us" widget starts one.
            const created = this.addConversation({
                id: newId("conv"),
                channel: data.channel ?? "web",
                state: "pending",
                participants: [this.me],
                capabilities: { composer: { mode: "free" } },
                ...this.newConversation,
            });
            data = { conversation: created.id, limit: data.limit };
            this.onStart?.(created, this);
        }
        const conversation = this.conversations.get(data.conversation);
        if (!conversation) {
            this.answer("error", { code: "not_found" }, frame.id);
            return;
        }
        this.answer("ack", { conversation: conversation.id }, frame.id);
        this.emit("conversation.created", conversation);
        // Its latest messages (protocol section 7.3).
        COMMANDS["history.fetch"].call(
            this,
            { conversation: data.conversation, limit: data.limit },
            { id: frame.id, quiet: true },
        );
    },
    "history.fetch"(data, frame) {
        const all = this.messages.get(data.conversation) ?? [];
        const end = data.before
            ? all.findIndex((message) => message.id === data.before)
            : all.length;
        const start = Math.max(0, end - (data.limit ?? 30));
        this.answer(
            "history",
            {
                conversation: data.conversation,
                messages: all.slice(start, end),
                before: start > 0 ? all[start].id : null,
                more: start > 0,
            },
            frame.id,
        );
        if (!frame.quiet) this.answer("ack", {}, frame.id);
    },
};
