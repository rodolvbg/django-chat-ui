import { describe, expect, it, vi } from "vitest";
import {
    ChatClient,
    CommandError,
} from "../../src/django_chat_ui/static/django_chat_ui/client.js";
import {
    FakeServer,
    MemoryTransport,
} from "../../src/django_chat_ui/static/django_chat_ui/transports/memory.js";
import { flush, ME, setup } from "./helpers.js";

const BOT = {
    id: "conv_bot",
    channel: "bot",
    participants: [ME, { id: "p_bot", kind: "bot", name: "Bot" }],
};

describe("ChatClient", () => {
    it("says hello with what it renders, and learns who it is", async () => {
        const { server, client } = await setup({ conversations: [[BOT]] });

        const [hello] = server.received;
        expect(hello.type).toBe("hello");
        expect(hello.data.protocol).toEqual(["1.0"]);
        expect(hello.data.capabilities.parts).toEqual(
            expect.arrayContaining(["text", "buttons", "template"]),
        );
        expect(hello.data.capabilities.streaming).toBe(true);
        expect(client.me).toEqual(ME);
        expect(client.protocol).toBe("1.0");
        // The conversations of `ready` are in their stores.
        expect(client.conversation("conv_bot").conversation.channel).toBe(
            "bot",
        );
    });

    it("lets its own capabilities override the defaults", async () => {
        const server = new FakeServer({ me: ME });
        const client = new ChatClient(new MemoryTransport(server), {
            capabilities: { parts: ["text"], "acme.order": { version: "2" } },
            client: { version: "9" },
        });
        await client.connect();
        expect(server.received[0].data.capabilities).toMatchObject({
            parts: ["text"],
            "acme.order": { version: "2" },
        });
        expect(server.received[0].data.client).toEqual({
            name: "django-chat-ui",
            version: "9",
        });
    });

    it("rejects a failed command with its error", async () => {
        const { client } = await setup();
        await expect(client.command("acme.unknown")).rejects.toMatchObject({
            code: "unknown_command",
        });
        await expect(client.open("missing")).rejects.toBeInstanceOf(
            CommandError,
        );
    });

    it("reports a transport failure as retryable", async () => {
        const transport = {
            connect: async () => {},
            send: () => Promise.reject(new Error("offline")),
            close() {},
        };
        const client = new ChatClient(transport);
        const error = await client.command("typing", {}).catch((e) => e);
        expect(error).toMatchObject({ code: "transport", retry: true });
        expect(new CommandError(undefined).message).toBe("error");
    });

    it("sends optimistically, then takes the server's copy", async () => {
        const { client } = await setup({ conversations: [[BOT]] });
        const store = client.conversation("conv_bot");

        const sending = client.send("conv_bot", [{ type: "text", text: "Hi" }]);
        expect(store.messages.at(-1)).toMatchObject({
            status: "sending",
            author: "p_me",
        });
        await sending;
        await flush();

        expect(store.messages).toHaveLength(1);
        expect(store.messages[0]).toMatchObject({
            status: "sent",
            parts: [{ type: "text", text: "Hi" }],
        });
        expect(store.messages[0].id).toMatch(/^m_/);
    });

    it("marks a rejected message as failed, and retries it once", async () => {
        const { server, client } = await setup({ conversations: [[BOT]] });
        server.reject = () => ({
            code: "rate_limited",
            message: "Slow down",
            retry: true,
        });
        const store = client.conversation("conv_bot");

        await expect(
            client.send("conv_bot", [{ type: "text", text: "Hi" }], {
                replyTo: "m_0",
            }),
        ).rejects.toMatchObject({ code: "rate_limited" });
        const [failed] = store.messages;
        expect(failed).toMatchObject({
            status: "failed",
            error: { message: "Slow down" },
        });

        server.reject = null;
        await client.retry("conv_bot", failed.clientId);
        await flush();
        expect(store.messages).toHaveLength(1);
        expect(store.messages[0]).toMatchObject({
            status: "sent",
            replyTo: "m_0",
        });

        // The same clientId again: the server doesn't add it twice.
        await client.send("conv_bot", [{ type: "text", text: "Hi" }], {
            clientId: failed.clientId,
        });
        await flush();
        expect(server.messages.get("conv_bot")).toHaveLength(1);

        await expect(client.retry("conv_bot", "c_none")).rejects.toMatchObject({
            code: "not_found",
        });
    });

    it("sends the other commands", async () => {
        const { server, client } = await setup({ conversations: [[BOT]] });
        await client.action("conv_bot", "m_1", "yes");
        await client.read("conv_bot", "m_1");
        await client.typing("conv_bot", true);
        await client.open("conv_bot");
        await client.history("conv_bot", 5);
        client.conversation("conv_bot").before = "m_1";
        await client.history("conv_bot");

        expect(
            server.received.slice(1).map((frame) => [frame.type, frame.data]),
        ).toEqual([
            [
                "action",
                { conversation: "conv_bot", message: "m_1", button: "yes" },
            ],
            ["message.read", { conversation: "conv_bot", until: "m_1" }],
            ["typing", { conversation: "conv_bot", active: true }],
            ["conversation.open", { conversation: "conv_bot", limit: 30 }],
            ["history.fetch", { conversation: "conv_bot", limit: 5 }],
            [
                "history.fetch",
                { conversation: "conv_bot", limit: 30, before: "m_1" },
            ],
        ]);
    });

    it("routes events to their conversation, and dispatches every frame", async () => {
        const { server, client } = await setup();
        const frames = vi.fn();
        client.addEventListener("frame", (event) => frames(event.detail.type));

        server.addConversation({ id: "c_new" });
        server.emit("conversation.created", { id: "c_new", title: "New" });
        server.post("c_unknown", "p_x", [{ type: "text", text: "lost" }]);
        await flush();

        expect(client.conversation("c_new").conversation.title).toBe("New");
        expect(client.stores.has("c_unknown")).toBe(false);
        expect(frames).toHaveBeenCalledWith("conversation.created");
        expect(frames).toHaveBeenCalledWith("message.created");
    });

    it("resumes after reconnecting, getting what it missed", async () => {
        const { server, client } = await setup({ conversations: [[BOT]] });
        server.post("conv_bot", "p_bot", [{ type: "text", text: "one" }]);
        await flush();
        // The message, and the conversation's update (its last message).
        expect(client.seq).toBe(2);

        client.close();
        server.post("conv_bot", "p_bot", [{ type: "text", text: "two" }]);
        const ready = await client.connect();
        await flush();

        expect(ready.resumed).toBe(true);
        expect(server.received.at(-1).data.resume).toEqual({ seq: 2 });
        expect(
            client
                .conversation("conv_bot")
                .messages.map((m) => m.parts[0].text),
        ).toEqual(["one", "two"]);
    });

    it("holds commands sent while connecting until after the hello", async () => {
        // Sent before the hello, a command would go without the session the
        // hello settles: it could be someone else's (a new visitor).
        let open;
        const sent = [];
        const transport = {
            onFrame: null,
            connect(onFrame) {
                this.onFrame = onFrame;
                return new Promise((resolve) => {
                    open = resolve;
                });
            },
            async send(frame) {
                sent.push(frame.type);
                const data =
                    frame.type === "hello" ? { me: ME, protocol: "1.0" } : {};
                this.onFrame({
                    type: frame.type === "hello" ? "ready" : "ack",
                    ref: frame.id,
                    data,
                });
            },
            close() {},
        };
        const client = new ChatClient(transport);
        const connecting = client.connect();
        const started = client.command("conversation.open", { with: [] });
        await flush();
        expect(sent).toEqual([]); // the stream isn't open yet: nothing goes

        open();
        await connecting;
        await started;
        expect(sent).toEqual(["hello", "conversation.open"]);

        // A failed connection doesn't hold them forever.
        const failing = new ChatClient({
            connect: () => Promise.reject(new Error("offline")),
            send: () => Promise.reject(new Error("offline")),
            close() {},
        });
        await expect(failing.connect()).rejects.toThrow("offline");
        await expect(failing.command("typing", {})).rejects.toMatchObject({
            code: "transport",
        });
    });

    it("ignores an answer to nothing", async () => {
        const { client } = await setup();
        expect(() =>
            client.receive({ type: "ack", ref: "nobody", data: {} }),
        ).not.toThrow();
        expect(() => client.receive({ type: "ack", data: {} })).not.toThrow();
    });
});
