import { afterEach, describe, expect, it, vi } from "vitest";

const TEXTS = {
    thread: { send: "Enviar" },
    inbox: { search: "Buscar" },
    widget: { open: "Escríbenos" },
};

function page(html, config) {
    document.body.innerHTML = html;
    if (config) {
        const node = document.createElement("script");
        node.id = "chat-ui-config";
        node.type = "application/json";
        node.textContent =
            typeof config === "string" ? config : JSON.stringify(config);
        document.body.append(node);
    }
}

afterEach(() => {
    document.body.replaceChildren();
    vi.resetModules();
    vi.unstubAllGlobals();
});

class Source {
    constructor(url) {
        this.url = url;
        Source.last = this;
    }
    close() {}
}

describe("boot.js", () => {
    it("connects the page's components, with their texts and the uploader", async () => {
        vi.stubGlobal("EventSource", Source);
        vi.stubGlobal(
            "fetch",
            vi.fn(() => new Promise(() => {})),
        );
        page(
            "<chat-inbox></chat-inbox><chat-widget></chat-widget><chat-thread conversation='1'></chat-thread>",
            {
                events: "/chat/events",
                commands: "/chat/commands",
                uploads: "/chat/uploads",
                csrfToken: "t",
                transport: "sse",
                texts: TEXTS,
            },
        );

        const { client, config } = await import(
            "../../src/django_chat_ui/static/django_chat_ui/boot.js"
        );

        expect(config.events).toBe("/chat/events");
        expect(Source.last.url).toBe("/chat/events");
        const inbox = document.querySelector("chat-inbox");
        const widget = document.querySelector("chat-widget");
        const thread = document.body.querySelector(":scope > chat-thread");
        for (const element of [inbox, widget, thread]) {
            expect(element.client).toBe(client);
            expect(typeof element.uploader).toBe("function");
        }
        expect(inbox.texts.search).toBe("Buscar");
        expect(inbox.texts.send).toBe("Enviar");
        expect(widget.texts.open).toBe("Escríbenos");
        expect(thread.texts.send).toBe("Enviar");
        // Their own threads got theirs from them.
        expect(inbox.querySelector("chat-thread").client).toBe(client);
        expect(inbox.querySelector("chat-thread").uploader).toBe(
            inbox.uploader,
        );
    });

    it("polls when told", async () => {
        const fetch = vi.fn(() => new Promise(() => {}));
        vi.stubGlobal("fetch", fetch);
        page("<chat-thread></chat-thread>", {
            events: "/e",
            commands: "/c",
            uploads: "/u",
            transport: "polling",
            poll: 2000,
            texts: {},
        });
        const { client } = await import(
            "../../src/django_chat_ui/static/django_chat_ui/boot.js"
        );
        expect(client.transport.poll).toBe(2000);
        expect(fetch.mock.calls[0][0]).toBe("/e");
    });

    it("speaks over a WebSocket when told", async () => {
        const sockets = [];
        vi.stubGlobal(
            "WebSocket",
            class {
                constructor(url) {
                    sockets.push(url);
                }
                close() {}
            },
        );
        page("", {
            events: "/e",
            commands: "/c",
            uploads: "/u",
            websocket: "/chat/ws",
            transport: "websocket",
            texts: {},
        });
        const { client } = await import(
            "../../src/django_chat_ui/static/django_chat_ui/boot.js"
        );
        expect(client.transport.constructor.name).toBe("WebSocketTransport");
        expect(sockets).toEqual([`ws://${location.host}/chat/ws`]);
    });

    it("does nothing without its configuration", async () => {
        page("<chat-thread></chat-thread>");
        const { client, attach } = await import(
            "../../src/django_chat_ui/static/django_chat_ui/boot.js"
        );
        expect(client).toBeNull();
        const thread = document.querySelector("chat-thread");
        attach(thread);
        expect(thread.client).toBeNull();
    });

    it("does nothing with a broken one", async () => {
        page("", "{");
        const { client } = await import(
            "../../src/django_chat_ui/static/django_chat_ui/boot.js"
        );
        expect(client).toBeNull();
    });

    it("says when it can't connect", async () => {
        const error = vi.spyOn(console, "error").mockImplementation(() => {});
        vi.stubGlobal(
            "fetch",
            vi.fn(() => Promise.reject(new Error("offline"))),
        );
        // A configuration without texts: the components keep their own.
        page("<chat-thread></chat-thread>", {
            events: "/e",
            commands: "/c",
            uploads: "/u",
            transport: "polling",
            poll: 1000,
        });
        await import("../../src/django_chat_ui/static/django_chat_ui/boot.js");
        await new Promise((resolve) => setTimeout(resolve, 0));
        expect(document.querySelector("chat-thread").texts.send).toBe("Send");
        expect(error).toHaveBeenCalledWith(
            "django-chat-ui: can't connect.",
            expect.any(Error),
        );
        const { client } = await import(
            "../../src/django_chat_ui/static/django_chat_ui/boot.js"
        );
        client.close();
    });
});
