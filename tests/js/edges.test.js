/**
 * The edges: what a server may leave out (the protocol's fields are
 * optional), and the components set up in any order.
 */
import { afterEach, describe, expect, it, vi } from "vitest";
import {
    INBOX_TEXTS,
    preview,
} from "../../src/django_chat_ui/static/django_chat_ui/chat-inbox.js";
import "../../src/django_chat_ui/static/django_chat_ui/chat-widget.js";
import { ChatClient } from "../../src/django_chat_ui/static/django_chat_ui/client.js";
import { format } from "../../src/django_chat_ui/static/django_chat_ui/dom.js";
import { renderPart } from "../../src/django_chat_ui/static/django_chat_ui/parts.js";
import { ConversationStore } from "../../src/django_chat_ui/static/django_chat_ui/store.js";
import {
    FakeServer,
    MemoryTransport,
} from "../../src/django_chat_ui/static/django_chat_ui/transports/memory.js";
import { WebSocketTransport } from "../../src/django_chat_ui/static/django_chat_ui/transports/websocket.js";
import { flush, ME, setup } from "./helpers.js";

const ANA = { id: "p_ana", kind: "contact", name: "Ana" };
const at = "2026-10-20T10:00:00Z";

afterEach(() => {
    document.body.replaceChildren();
});

describe("what a server may leave out", () => {
    it("a frame without data, an error without its data", async () => {
        const { client } = await setup({
            conversations: [[{ id: "c", channel: "web" }]],
        });
        expect(() =>
            client.receive({ type: "conversation.updated" }),
        ).not.toThrow();
        const answer = client.command("typing", {}, "cmd_x");
        client.receive({ type: "error", ref: "cmd_x" });
        await expect(answer).rejects.toMatchObject({ detail: {} });
    });

    it("messages without parts", () => {
        const store = new ConversationStore("c");
        store.apply({
            type: "message.created",
            data: { id: "m", conversation: "c", createdAt: at },
        });
        store.apply({
            type: "history",
            data: { conversation: "c", messages: [{ id: "h", createdAt: at }] },
        });
        expect(store.messages.map((m) => m.parts)).toEqual([[], []]);
    });

    it("the texts to fill in", () => {
        expect(format("%(name)s is typing…", {})).toBe(" is typing…");
    });

    it("links without their text, sizes of nothing", () => {
        const context = { texts: {} };
        const link = renderPart(
            { type: "link", url: "https://shop.example/a" },
            context,
        );
        expect(link.textContent).toContain("https://shop.example/a");
        const file = renderPart({ type: "file" }, context);
        expect(file.textContent).toBe("");
        const card = renderPart(
            { type: "card", url: "https://shop.example/c" },
            context,
        );
        expect(card.querySelector("a").textContent).toBe(
            "https://shop.example/c",
        );
        const unsafe = renderPart(
            { type: "link", url: "javascript:alert(1)" },
            context,
        );
        expect(unsafe.querySelector("a")).toBeNull();
        expect(unsafe.textContent).toBe("javascript:alert(1)");
    });

    it("previews of files without a name", () => {
        expect(
            preview({ parts: [{ type: "file", url: "/f" }] }, INBOX_TEXTS),
        ).toBe("");
    });

    it("conversations without participants or title", async () => {
        const { client } = await setup({
            conversations: [[{ id: "c", channel: "web" }]],
        });
        const inbox = document.createElement("chat-inbox");
        document.body.append(inbox);
        inbox.client = client;
        const item = inbox.querySelector(".chat-conversation");
        expect(item.querySelector(".chat-conversation-title").textContent).toBe(
            "",
        );
        expect(item.querySelector(".chat-avatar").textContent).toBe("");
        inbox.selected = "c";
        expect(inbox.querySelector(".chat-inbox-subtitle").textContent).toBe(
            "web",
        );
        const search = inbox.querySelector(".chat-inbox-search");
        search.value = "x";
        search.dispatchEvent(new Event("input"));
        expect(inbox.querySelectorAll(".chat-conversation")).toHaveLength(0);
    });
});

describe("components set up in any order", () => {
    it("an inbox given its client and uploader before it's on the page", async () => {
        const { client } = await setup();
        const inbox = document.createElement("chat-inbox");
        const uploader = vi.fn();
        inbox.uploader = uploader;
        inbox.client = client;
        document.body.append(inbox);
        expect(inbox.querySelector("chat-thread").uploader).toBe(uploader);
        expect(inbox.querySelector("chat-thread").client).toBe(client);
    });

    it("a widget given them before it's on the page, and a new client", async () => {
        const { client } = await setup();
        const widget = document.createElement("chat-widget");
        const uploader = vi.fn();
        widget.client = client; // no badge yet: nothing to show
        widget.uploader = uploader;
        document.body.append(widget);
        const thread = widget.querySelector("chat-thread");
        expect(thread.client).toBe(client);
        expect(thread.uploader).toBe(uploader);

        const other = new ChatClient(
            new MemoryTransport(new FakeServer({ me: ME })),
        );
        widget.client = other;
        expect(thread.client).toBe(other);
    });

    it("a thread moved to another place of the page", async () => {
        const { thread } = await setup({
            conversations: [
                [{ id: "c", channel: "web", participants: [ME, ANA] }, []],
            ],
            thread: "c",
        });
        const shell = thread.querySelector(".chat-thread");
        const box = document.createElement("div");
        document.body.append(box);
        box.append(thread);
        expect(thread.querySelector(".chat-thread")).toBe(shell);
    });
});

describe("a thread's edges", () => {
    async function thread(capabilities, messages = []) {
        const conversation = {
            id: "c",
            channel: "web",
            participants: [ME, ANA],
            capabilities,
        };
        return setup({
            conversations: [[conversation, messages]],
            thread: "c",
        });
    }

    it("a status of its own, a reaction of someone unknown", async () => {
        const { thread: element } = await thread(
            { receipts: true, reactions: true },
            [
                {
                    id: "m",
                    conversation: "c",
                    author: "p_me",
                    createdAt: at,
                    status: "acme.queued",
                    parts: [{ type: "text", text: "Hi" }],
                    reactions: [{ emoji: "👍", by: ["p_gone"] }],
                },
            ],
        );
        const status = element.querySelector(".chat-status");
        expect(status.textContent).toBe("");
        expect(status.title).toBe("acme.queued");
        expect(element.querySelector(".chat-reaction").title).toBe("?");
    });

    it("a longest message", async () => {
        const { thread: element } = await thread({
            composer: { mode: "free", maxLength: 280 },
        });
        expect(element.querySelector(".chat-input").maxLength).toBe(280);
    });

    it("templates without names, previews or params; or none", async () => {
        const templates = [
            { id: "plain" },
            {
                id: "named",
                name: "Named",
                preview: "Hi {{name}} {{2}}",
                params: ["name"],
            },
        ];
        const { server, thread: element } = await thread({
            composer: { mode: "templates", templates },
        });
        const select = element.querySelector(".chat-template");
        expect([...select.options].map((o) => o.textContent)).toEqual([
            "plain",
            "Named",
        ]);
        expect(
            element.querySelector(".chat-template-preview").textContent,
        ).toBe("");
        expect(element.querySelector(".chat-composer-note")).toBeNull(); // no reason given

        select.value = "named";
        select.dispatchEvent(new Event("change"));
        const param = element.querySelector(".chat-template-param");
        param.value = "Ana";
        param.dispatchEvent(new Event("input"));
        expect(
            element.querySelector(".chat-template-preview").textContent,
        ).toBe("Hi Ana {{2}}");

        element.querySelector(".chat-send").click();
        await flush();
        const sent = server.received.filter((f) => f.type === "message.send");
        expect(sent.at(-1).data.parts[0]).toMatchObject({
            template: "named",
            fallback: "Hi Ana {{2}}",
        });
    });

    it("templates only, but none to send", async () => {
        const { server, thread: element } = await thread({
            composer: { mode: "templates" },
        });
        expect(element.querySelectorAll(".chat-template option")).toHaveLength(
            0,
        );
        element.querySelector(".chat-send").click();
        await flush();
        expect(server.received.some((f) => f.type === "message.send")).toBe(
            false,
        );
    });

    it("finds nothing to focus again when its message is gone", async () => {
        const { thread: element } = await thread({});
        expect(() =>
            element.refocus({ message: "gone", className: "chat-react" }),
        ).not.toThrow();
    });
});

describe("transports' edges", () => {
    it("a fake server's frames without data, commands of unknown conversations", async () => {
        const server = new FakeServer({ me: ME });
        const transport = new MemoryTransport(server);
        const frames = [];
        await transport.connect((frame) => frames.push(frame));
        server.receive({ type: "typing", id: "1" });
        server.receive({
            type: "message.send",
            id: "2",
            data: { conversation: "nope", clientId: "c", parts: [] },
        });
        server.receive({
            type: "history.fetch",
            id: "3",
            data: { conversation: "nope" },
        });
        await flush();
        expect(
            frames.find((f) => f.ref === "3" && f.type === "history").data
                .messages,
        ).toEqual([]);
        expect(server.emit("typing", {}).ref).toBeUndefined();
        expect(server.emit("typing", {}, "r").ref).toBe("r");
    });

    it("a WebSocket resuming from where it was told, saying hello without data", async () => {
        const sockets = [];
        class Socket {
            constructor() {
                this.readyState = 1;
                this.sent = [];
                sockets.push(this);
                setTimeout(() => this.onopen?.());
            }
            send(text) {
                this.sent.push(JSON.parse(text));
            }
            close() {
                this.onclose?.();
            }
        }
        const transport = new WebSocketTransport({
            url: "ws://x",
            retry: 0,
            WebSocket: Socket,
        });
        await transport.connect(() => {}, { resume: { seq: 41 } });
        expect(transport.seq).toBe(41);
        await transport.send({ type: "hello", id: "h" });
        sockets[0].onclose(); // dropped: it says hello again
        await new Promise((resolve) => setTimeout(resolve, 10));
        expect(sockets[1].sent).toEqual([
            { type: "hello", id: "h-1", data: { resume: { seq: 41 } } },
        ]);
        transport.close();
    });
});
