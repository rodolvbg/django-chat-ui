import { afterEach, describe, expect, it, vi } from "vitest";
import { TEXTS } from "../../src/django_chat_ui/static/django_chat_ui/chat-thread.js";
import { registerPart, unregisterPart } from "../../src/django_chat_ui/static/django_chat_ui/parts.js";
import { ME, flush, messages, setup, text } from "./helpers.js";

const BOT = { id: "p_bot", kind: "bot", name: "Asistente" };
const ANA = { id: "p_ana", kind: "contact", name: "Ana García" };

const chatbot = {
    id: "conv_bot",
    channel: "bot",
    participants: [ME, BOT],
    capabilities: { streaming: true, buttons: true, composer: { mode: "free" } },
};

const whatsapp = {
    id: "conv_wa",
    channel: "whatsapp",
    participants: [ME, ANA],
    capabilities: { receipts: true, typing: true, composer: { mode: "free" } },
};

function type(thread, value) {
    const input = thread.querySelector(".chat-input");
    input.value = value;
    input.dispatchEvent(new Event("input"));
    return input;
}

function enter(input, options = {}) {
    input.dispatchEvent(new KeyboardEvent("keydown", { key: "Enter", bubbles: true, cancelable: true, ...options }));
}

afterEach(() => {
    document.body.replaceChildren();
    vi.useRealTimers();
});

describe("<chat-thread> with a chatbot", () => {
    it("streams the bot's answer, and its quick replies act", async () => {
        const { server, client, thread } = await setup({ conversations: [[chatbot]], thread: "conv_bot" });
        server.onMessage = (message, srv) => {
            srv.stream("conv_bot", "p_bot", ["Tu pedido ", "sale hoy."], {
                parts: [
                    { type: "text", text: "Tu pedido sale hoy." },
                    { type: "buttons", buttons: [{ id: "human", label: "Hablar con alguien" }], fallback: "Hablar con alguien" },
                ],
            });
        };
        server.onAction = (data, srv) => srv.post("conv_bot", "p_bot", [{ type: "text", text: `Vale (${data.button})` }]);

        // What the thread showed after each change: streaming at some point.
        const streaming = [];
        client.conversation("conv_bot").addEventListener("change", () => {
            streaming.push(Boolean(thread.querySelector(".chat-message--streaming .chat-text")?.textContent));
        });

        enter(type(thread, "¿Dónde está mi pedido?"));
        // At once, before the server answers: the message, as "sending".
        expect(text(messages(thread)[0])).toContain("¿Dónde está mi pedido?");
        expect(messages(thread)[0].dataset.status).toBe("sending");
        expect(thread.querySelector(".chat-input").value).toBe("");

        await flush(20);
        expect(streaming).toContain(true);

        const [mine, answer] = messages(thread);
        expect(mine.className).toContain("chat-message--own");
        expect(mine.dataset.status).toBe("sent");
        // No receipts on this channel: no ✓ marks.
        expect(mine.querySelector(".chat-status")).toBeNull();
        expect(answer.className).toContain("chat-message--bot");
        expect(answer.className).not.toContain("streaming");
        expect(answer.querySelector(".chat-author").textContent).toBe("Asistente");
        expect(answer.querySelector(".chat-text").textContent).toBe("Tu pedido sale hoy.");

        const button = answer.querySelector(".chat-button");
        button.click();
        expect(answer.isConnected ? thread.querySelector(".chat-button").disabled : true).toBe(true);
        await flush();
        expect(server.received.find((frame) => frame.type === "action").data).toEqual({
            conversation: "conv_bot",
            message: answer.dataset.id,
            button: "human",
        });
        expect(text(messages(thread).at(-1))).toContain("Vale (human)");
        expect(client.conversation("conv_bot").messages).toHaveLength(3);
    });

    it("sends with Enter, not with Shift+Enter or when empty", async () => {
        const { server, thread } = await setup({ conversations: [[chatbot]], thread: "conv_bot" });
        enter(type(thread, "  "));
        enter(type(thread, "line"), { shiftKey: true });
        enter(type(thread, "line"), { isComposing: true });
        thread.querySelector(".chat-input").dispatchEvent(new KeyboardEvent("keydown", { key: "a" }));
        await flush();
        expect(server.received.filter((f) => f.type === "message.send")).toHaveLength(0);

        thread.querySelector(".chat-send").click();
        await flush();
        expect(server.received.filter((f) => f.type === "message.send")).toHaveLength(1);
    });

    it("only offers the buttons when the composer is 'actions'", async () => {
        const { thread } = await setup({
            conversations: [[{ ...chatbot, capabilities: { composer: { mode: "actions" } } }]],
            thread: "conv_bot",
        });
        expect(thread.querySelector(".chat-input")).toBeNull();
        expect(thread.querySelector(".chat-composer-note").textContent).toBe(TEXTS.actionsOnly);
        thread.querySelector(".chat-composer").dispatchEvent(new Event("submit", { cancelable: true }));
    });
});

describe("<chat-thread> with WhatsApp", () => {
    it("shows receipts, typing, and templates once the window closes", async () => {
        const { server, thread } = await setup({ conversations: [[whatsapp]], thread: "conv_wa" });

        enter(type(thread, "Hola Ana"));
        await flush();
        const mine = () => messages(thread)[0];
        expect(mine().querySelector(".chat-status").textContent).toBe("✓");
        const id = mine().dataset.id;
        server.emit("message.updated", { id, conversation: "conv_wa", status: "delivered" });
        await flush();
        expect(mine().querySelector(".chat-status").textContent).toBe("✓✓");
        server.emit("message.updated", { id, conversation: "conv_wa", status: "read" });
        await flush();
        expect(mine().querySelector(".chat-status--read").title).toBe("Read");

        server.emit("typing", { conversation: "conv_wa", participant: "p_ana", active: true });
        await flush();
        expect(thread.querySelector(".chat-typing").textContent).toBe("Ana García is typing…");
        server.emit("typing", { conversation: "conv_wa", participant: "p_x", active: true });
        await flush();
        expect(thread.querySelector(".chat-typing").textContent).toBe(TEXTS.typingMany);
        server.emit("typing", { conversation: "conv_wa", participant: "p_x", active: false });
        server.emit("typing", { conversation: "conv_wa", participant: "p_ana", active: false });
        await flush();
        expect(thread.querySelector(".chat-typing").textContent).toBe("");

        server.update("conv_wa", {
            capabilities: {
                receipts: true,
                composer: {
                    mode: "templates",
                    reason: "Han pasado más de 24 horas.",
                    templates: [
                        { id: "followup", name: "Seguimiento", preview: "Hola {{1}}, ¿te ayudamos en {{2}}?", params: ["name", "topic"] },
                        { id: "bye", name: "Despedida", preview: "Hasta pronto." },
                    ],
                },
            },
        });
        await flush();

        expect(thread.querySelector(".chat-input")).toBeNull();
        expect(thread.querySelector(".chat-composer-note").textContent).toBe("Han pasado más de 24 horas.");
        const [name, topic] = thread.querySelectorAll(".chat-template-param");
        const preview = thread.querySelector(".chat-template-preview");
        expect(preview.textContent).toBe("Hola {{1}}, ¿te ayudamos en {{2}}?");
        name.value = "Ana";
        name.dispatchEvent(new Event("input"));
        expect(preview.textContent).toBe("Hola Ana, ¿te ayudamos en {{2}}?");
        topic.value = "tu pedido";
        topic.dispatchEvent(new Event("input"));

        thread.querySelector(".chat-send").click();
        await flush();
        const sent = server.received.filter((f) => f.type === "message.send").at(-1);
        expect(sent.data.parts).toEqual([
            { type: "template", template: "followup", params: { name: "Ana", topic: "tu pedido" }, fallback: "Hola Ana, ¿te ayudamos en tu pedido?" },
        ]);
        expect(text(messages(thread).at(-1))).toContain("Hola Ana, ¿te ayudamos en tu pedido?");

        // Another template, without params.
        const select = thread.querySelector(".chat-template");
        select.value = "bye";
        select.dispatchEvent(new Event("change"));
        expect(thread.querySelectorAll(".chat-template-param")).toHaveLength(0);
        expect(preview.isConnected ? preview.textContent : thread.querySelector(".chat-template-preview").textContent).toBe("Hasta pronto.");
    });

    it("tells the server it's typing, then that it stopped", async () => {
        vi.useFakeTimers({ toFake: ["setTimeout", "clearTimeout"], shouldAdvanceTime: true });
        const { server, thread } = await setup({ conversations: [[whatsapp]], thread: "conv_wa" });
        type(thread, "H");
        type(thread, "Ho");
        await vi.advanceTimersByTimeAsync(3100);
        await flush();
        const typing = server.received.filter((f) => f.type === "typing").map((f) => f.data.active);
        expect(typing).toEqual([true, false]);

        type(thread, "Hola");
        enter(thread.querySelector(".chat-input"));
        await flush();
        expect(server.received.filter((f) => f.type === "typing").map((f) => f.data.active)).toEqual([true, false, true, false]);
    });

    it("shows a failed message with Retry", async () => {
        const { server, thread } = await setup({ conversations: [[whatsapp]], thread: "conv_wa" });
        server.reject = () => ({ code: "channel_error", message: "WhatsApp rejected it" });
        enter(type(thread, "Hola"));
        await flush();
        expect(messages(thread)[0].querySelector(".chat-status--failed").textContent).toBe("WhatsApp rejected it");

        server.reject = null;
        messages(thread)[0].querySelector(".chat-retry").click();
        await flush();
        expect(messages(thread)).toHaveLength(1);
        expect(messages(thread)[0].dataset.status).toBe("sent");
    });

    it("marks what it shows as read, once", async () => {
        const { server, thread } = await setup({ conversations: [[whatsapp]], thread: "conv_wa" });
        server.post("conv_wa", "p_ana", [{ type: "text", text: "Hola" }]);
        await flush();
        thread.render();
        await flush();
        const reads = server.received.filter((f) => f.type === "message.read");
        expect(reads).toHaveLength(1);
        expect(reads[0].data.until).toBe(messages(thread)[0].dataset.id);
    });
});

describe("<chat-thread>", () => {
    it("groups messages, names authors and centers system lines", async () => {
        const team = { id: "conv_team", channel: "internal", participants: [ME, ANA, { id: "p_luis", kind: "agent", name: "Luis" }] };
        const { server, thread } = await setup({ conversations: [[team]], thread: "conv_team" });
        server.post("conv_team", "p_ana", [{ type: "text", text: "uno" }]);
        server.post("conv_team", "p_ana", [{ type: "text", text: "dos" }]);
        server.post("conv_team", "p_luis", [{ type: "text", text: "tres" }]);
        server.post("conv_team", undefined, [{ type: "system", text: "Luis se unió" }]);
        server.post("conv_team", "p_ana", [{ type: "text", text: "cuatro" }], { editedAt: "2026-10-20T10:05:00Z" });
        await flush();

        const [one, two, three, system, four] = messages(thread);
        expect(one.querySelector(".chat-author").textContent).toBe("Ana García");
        expect(two.className).toContain("continued");
        expect(two.querySelector(".chat-author")).toBeNull();
        expect(three.className).toContain("chat-message--agent");
        expect(system.className).toContain("chat-message--system");
        expect(system.querySelector(".chat-meta")).toBeNull();
        expect(four.querySelector(".chat-edited").textContent).toBe("edited");
        expect(four.querySelector("time").dateTime).toBeTruthy();
        expect(thread.querySelector(".chat-log").getAttribute("role")).toBe("log");
    });

    it("renders an extension's part, or its fallback", async () => {
        const { server, thread } = await setup({ conversations: [[whatsapp]], thread: "conv_wa" });
        const order = { type: "acme.order", fallback: "Pedido A-1029", ext: { acme: { orderId: "A-1029" } } };
        server.post("conv_wa", "p_ana", [order]);
        await flush();
        expect(thread.querySelector(".chat-part--fallback").textContent).toBe("Pedido A-1029");

        registerPart("acme.order", (part) => {
            const card = document.createElement("div");
            card.className = "acme-order";
            card.textContent = `Order ${part.ext.acme.orderId}`;
            return card;
        });
        thread.render();
        expect(thread.querySelector(".acme-order").textContent).toBe("Order A-1029");
        unregisterPart("acme.order");
    });

    it("says why a closed conversation can't be written to", async () => {
        const closed = { ...whatsapp, capabilities: { composer: { mode: "closed", reason: "Archivada" } } };
        const { thread, server } = await setup({ conversations: [[closed]], thread: "conv_wa" });
        expect(thread.querySelector(".chat-composer-note").textContent).toBe("Archivada");

        // An extension's composer mode it doesn't know: closed.
        server.update("conv_wa", { capabilities: { composer: { mode: "acme.vote" } } });
        await flush();
        expect(thread.querySelector(".chat-composer").dataset.mode).toBe("acme.vote");
        expect(thread.querySelector(".chat-composer-note").textContent).toBe(TEXTS.closed);
    });

    it("loads earlier messages", async () => {
        const history = Array.from({ length: 35 }, (_, i) => ({
            id: `m_${String(i).padStart(2, "0")}`,
            conversation: "conv_wa",
            author: "p_ana",
            parts: [{ type: "text", text: `#${i}` }],
            createdAt: `2026-10-19T10:${String(i).padStart(2, "0")}:00Z`,
        }));
        const conversation = { ...whatsapp, capabilities: { history: true } };
        const { thread } = await setup({ conversations: [[conversation, history]], thread: "conv_wa" });
        // Opening it brought the latest 30.
        expect(messages(thread)).toHaveLength(30);
        expect(text(messages(thread)[0])).toContain("#5");
        const earlier = thread.querySelector(".chat-earlier");
        expect(earlier.hidden).toBe(false);

        earlier.click();
        await flush();
        expect(messages(thread)).toHaveLength(35);
        expect(text(messages(thread)[0])).toContain("#0");
        expect(earlier.hidden).toBe(true);
    });

    it("hides 'earlier' without history", async () => {
        const { thread } = await setup({ conversations: [[whatsapp]], thread: "conv_wa" });
        expect(thread.querySelector(".chat-earlier").hidden).toBe(true);
    });

    it("attaches files with an uploader", async () => {
        const withFiles = { ...whatsapp, capabilities: { attachments: { types: ["image", "file"] } } };
        const { server, thread } = await setup({ conversations: [[withFiles]], thread: "conv_wa" });
        expect(thread.querySelector(".chat-attach")).toBeNull(); // No uploader yet.

        thread.uploader = vi.fn(async (file) => ({ type: "file", url: `https://x/${file.name}`, name: file.name }));
        thread.render();
        const input = thread.querySelector(".chat-file-input");
        expect(input.accept).toBe("image/*");
        const click = vi.spyOn(input, "click").mockImplementation(() => {});
        thread.querySelector(".chat-attach").click();
        expect(click).toHaveBeenCalled();

        Object.defineProperty(input, "files", { configurable: true, value: [new File(["x"], "a.pdf")] });
        input.dispatchEvent(new Event("change"));
        await flush();
        expect(server.received.filter((f) => f.type === "message.send").at(-1).data.parts).toEqual([
            { type: "file", url: "https://x/a.pdf", name: "a.pdf" },
        ]);

        Object.defineProperty(input, "files", { configurable: true, value: [] });
        input.dispatchEvent(new Event("change"));
        thread.uploader = vi.fn(async () => null);
        thread.render();
        const again = thread.querySelector(".chat-file-input");
        Object.defineProperty(again, "files", { configurable: true, value: [new File(["x"], "b.pdf")] });
        again.dispatchEvent(new Event("change"));
        await flush();
        expect(server.received.filter((f) => f.type === "message.send")).toHaveLength(1);
    });

    it("uses its own texts", async () => {
        const { thread } = await setup({ conversations: [[whatsapp]], thread: "conv_wa" });
        thread.texts = { placeholder: "Escribe un mensaje…", send: "Enviar" };
        expect(thread.querySelector(".chat-input").placeholder).toBe("Escribe un mensaje…");
        expect(thread.querySelector(".chat-send").textContent).toBe("Enviar");
        expect(thread.texts.retry).toBe(TEXTS.retry);
    });

    it("waits for a client and a conversation, and follows a new one", async () => {
        const { client } = await setup({ conversations: [[whatsapp], [chatbot]] });
        const thread = document.createElement("chat-thread");
        thread.client = client; // Not in the page yet: nothing to render.
        expect(thread.store).toBeNull();
        document.body.append(thread);
        expect(thread.store).toBeNull(); // No conversation attribute.
        thread.setAttribute("conversation", "conv_wa");
        expect(thread.store.id).toBe("conv_wa");
        thread.setAttribute("conversation", "conv_bot");
        expect(thread.store.id).toBe("conv_bot");
        expect(thread.client).toBe(client);
        thread.remove();
        thread.render();
    });

    it("keeps the message being typed while other things change", async () => {
        const { server, thread } = await setup({ conversations: [[whatsapp]], thread: "conv_wa" });
        const input = type(thread, "a medias");
        server.post("conv_wa", "p_ana", [{ type: "text", text: "¿Sigues ahí?" }]);
        await flush();
        expect(thread.querySelector(".chat-input")).toBe(input);
        expect(input.value).toBe("a medias");
    });
});

describe("<chat-thread> opening its conversation", () => {
    it("waits for the session, then brings its latest messages", async () => {
        const { ChatClient } = await import("../../src/django_chat_ui/static/django_chat_ui/client.js");
        const { FakeServer, MemoryTransport } = await import("../../src/django_chat_ui/static/django_chat_ui/transports/memory.js");
        const server = new FakeServer({ me: ME });
        server.addConversation(chatbot, [
            { id: "b1", conversation: "conv_bot", author: "p_bot", createdAt: "2026-10-20T10:00:00Z", parts: [{ type: "text", text: "¡Hola!" }] },
        ]);
        const client = new ChatClient(new MemoryTransport(server));
        const thread = document.createElement("chat-thread");
        thread.setAttribute("conversation", "conv_bot");
        document.body.append(thread);
        thread.client = client; // Before connecting: it waits.
        expect(server.received).toHaveLength(0);

        await client.connect();
        await flush();
        expect(server.received.map((f) => f.type)).toEqual(["hello", "conversation.open", "message.read"]);
        expect(text(messages(thread)[0])).toContain("¡Hola!");

        // Opened once, however many times it binds.
        thread.setAttribute("conversation", "conv_bot");
        await flush();
        expect(server.received.filter((f) => f.type === "conversation.open")).toHaveLength(1);
    });

    it("tries again later if opening failed", async () => {
        const { client, thread } = await setup({ conversations: [[chatbot]] });
        const missing = document.createElement("chat-thread");
        missing.setAttribute("conversation", "conv_missing");
        document.body.append(missing);
        missing.client = client;
        await flush();
        expect(client.conversation("conv_missing").opened).toBe(false);
        expect(thread).toBeNull();
    });
});
