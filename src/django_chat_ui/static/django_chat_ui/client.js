/**
 * A session of the chat UI protocol over a transport: hello/ready, commands
 * answered by ack or error, one store per conversation, optimistic sending
 * and resuming after a reconnection.
 *
 * A transport is any object with:
 *   connect(onFrame, { resume })  start receiving frames (a promise)
 *   send(frame)                   send one (a promise)
 *   close()
 */

import { registeredParts } from "./parts.js";
import { newId, PROTOCOL_VERSIONS } from "./protocol.js";
import { ConversationStore } from "./store.js";

export class CommandError extends Error {
    constructor(error) {
        super(error?.message ?? error?.code ?? "error");
        this.code = error?.code;
        this.retry = Boolean(error?.retry);
        this.detail = error;
    }
}

export class ChatClient extends EventTarget {
    /**
     * @param transport  see above
     * @param options.capabilities  what this client renders (section 6.2);
     *   `parts` defaults to every part type registered in parts.js
     * @param options.client  `{ name, version }` sent in hello
     */
    constructor(transport, { capabilities = {}, client = {} } = {}) {
        super();
        this.transport = transport;
        this.capabilities = capabilities;
        this.clientInfo = { name: "django-chat-ui", ...client };
        this.me = null;
        this.protocol = null;
        this.sessionCapabilities = {};
        this.stores = new Map();
        this.pending = new Map();
        this.seq = null;
        this.connecting = null;
    }

    /** Connect and say hello; resolves with the `ready` data. Commands
     * sent meanwhile wait for it: the session (who this client is) is
     * settled by then — sent before, a command could be someone else's. */
    connect() {
        const connecting = this.hello();
        this.connecting = connecting;
        return connecting;
    }

    async hello() {
        const resume = this.seq === null ? undefined : { seq: this.seq };
        await this.transport.connect((frame) => this.receive(frame), {
            resume,
        });
        const ready = await this.command("hello", {
            protocol: PROTOCOL_VERSIONS,
            client: this.clientInfo,
            capabilities: {
                parts: registeredParts(),
                streaming: true,
                formats: ["plain", "markdown"],
                ...this.capabilities,
            },
            ...(resume ? { resume } : {}),
        });
        return ready;
    }

    close() {
        this.transport.close();
    }

    /** The store of a conversation (created on first use). */
    conversation(id) {
        if (!this.stores.has(id)) {
            this.stores.set(id, new ConversationStore(id));
        }
        return this.stores.get(id);
    }

    /** Send a command; resolves on its ack (with `ready`'s data for hello),
     * rejects with a CommandError on its error. */
    command(type, data = {}, id = newId("cmd")) {
        const answer = new Promise((resolve, reject) => {
            this.pending.set(id, { resolve, reject, type });
        });
        // After the hello (if one is under way): see connect().
        const after =
            type === "hello" || !this.connecting
                ? Promise.resolve()
                : this.connecting.catch(() => {});
        after
            .then(() => this.transport.send({ type, id, data }))
            .catch((error) => {
                this.settle(id, null, {
                    code: "transport",
                    message: String(error),
                    retry: true,
                });
            });
        return answer;
    }

    receive(frame) {
        if (typeof frame.seq === "number") {
            this.seq = frame.seq;
        }
        if (frame.type === "ready") {
            this.me = frame.data.me;
            this.protocol = frame.data.protocol;
            this.sessionCapabilities = frame.data.capabilities ?? {};
            for (const conversation of frame.data.conversations ?? []) {
                this.conversation(conversation.id).apply({
                    type: "conversation.created",
                    data: conversation,
                });
            }
            this.settle(frame.ref, frame.data);
            this.dispatchEvent(new Event("ready"));
        } else if (frame.type === "ack") {
            this.settle(frame.ref, frame.data);
        } else if (frame.type === "error") {
            // An error without its data is still an error.
            this.settle(frame.ref, null, frame.data ?? {});
        }
        this.route(frame);
        this.dispatchEvent(new CustomEvent("frame", { detail: frame }));
    }

    settle(ref, data, error) {
        const pending = ref && this.pending.get(ref);
        if (!pending) return;
        this.pending.delete(ref);
        if (error) {
            pending.reject(new CommandError(error));
        } else {
            pending.resolve(data);
        }
    }

    /** Hand an event to the stores it concerns. */
    route(frame) {
        const data = frame.data ?? {};
        const id = frame.type.startsWith("conversation.")
            ? data.id
            : data.conversation;
        let changed = false;
        if (frame.type === "conversation.created" && id) {
            changed = this.conversation(id).apply(frame);
        } else if (id && this.stores.has(id)) {
            changed = this.stores.get(id).apply(frame);
        }
        if (
            changed &&
            (frame.type.startsWith("conversation.") ||
                frame.type === "message.created")
        ) {
            // The list of conversations changed (an inbox follows it).
            this.dispatchEvent(new Event("conversations"));
        }
    }

    /** The client's conversations, the latest active first. */
    list() {
        const updated = (store) =>
            store.lastMessage?.createdAt ?? store.conversation.updatedAt ?? "";
        return [...this.stores.values()]
            .filter((store) => store.conversation.channel !== undefined)
            .sort((a, b) => (updated(a) < updated(b) ? 1 : -1));
    }

    // Commands -------------------------------------------------------------

    /** Send a message: shown at once as "sending", confirmed by the server's
     * message.created (same clientId), or marked "failed". */
    async send(conversation, parts, { replyTo, clientId = newId("c") } = {}) {
        const store = this.conversation(conversation);
        if (!store.findByClientId(clientId)) {
            store.addPending({
                id: clientId,
                clientId,
                conversation,
                author: this.me?.id,
                parts,
                replyTo,
                createdAt: new Date().toISOString(),
            });
        }
        try {
            await this.command("message.send", {
                conversation,
                clientId,
                parts,
                ...(replyTo ? { replyTo } : {}),
            });
        } catch (error) {
            store.fail(clientId, error.detail);
            throw error;
        }
        return clientId;
    }

    /** Send a failed message again (same clientId: never sent twice). */
    retry(conversation, clientId) {
        const message =
            this.conversation(conversation).findByClientId(clientId);
        if (!message) {
            return Promise.reject(new CommandError({ code: "not_found" }));
        }
        message.status = "sending";
        this.conversation(conversation).changed();
        return this.send(conversation, message.parts, {
            replyTo: message.replyTo,
            clientId,
        });
    }

    action(conversation, message, button) {
        return this.command("action", { conversation, message, button });
    }

    /** React to a message with `emoji` (or take the reaction back). */
    react(message, emoji, active = true) {
        return this.command("message.react", { id: message, emoji, active });
    }

    read(conversation, until) {
        return this.command("message.read", { conversation, until });
    }

    typing(conversation, active) {
        return this.command("typing", { conversation, active });
    }

    /** Subscribe to a conversation: the server sends it and its latest
     * messages. */
    open(conversation, limit = 30) {
        return this.command("conversation.open", { conversation, limit });
    }

    /** Start a conversation with participants `with` (ids); resolves with
     * its id. */
    async start(participants = [], channel) {
        const answer = await this.command("conversation.open", {
            with: participants,
            ...(channel ? { channel } : {}),
        });
        return answer.conversation;
    }

    /** Fetch older messages (section 9). */
    history(conversation, limit = 30) {
        const store = this.conversation(conversation);
        return this.command("history.fetch", {
            conversation,
            limit,
            ...(store.before ? { before: store.before } : {}),
        });
    }
}
