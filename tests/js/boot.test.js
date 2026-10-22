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
    vi.restoreAllMocks();
});

async function boot() {
    return import("../../src/django_chat_ui/static/django_chat_ui/boot.js");
}

describe("boot.js", () => {
    it("connects the page's components, with their texts", async () => {
        const fetch = vi.fn(() => new Promise(() => {}));
        vi.stubGlobal("fetch", fetch);
        page(
            "<chat-inbox></chat-inbox><chat-widget></chat-widget><chat-thread conversation='!1:x'></chat-thread>",
            { baseUrl: "/chat", csrfToken: "t", poll: 0, texts: TEXTS },
        );
        const { client, config, attach } = await boot();
        expect(config.baseUrl).toBe("/chat");
        expect([client.baseUrl, client.csrfToken, client.poll]).toEqual([
            "/chat",
            "t",
            0,
        ]);
        expect(fetch.mock.calls[0][0]).toBe(
            "/chat/_matrix/client/v3/account/whoami",
        );

        const inbox = document.querySelector("chat-inbox");
        expect(inbox.client).toBe(client);
        expect(inbox.texts.search).toBe("Buscar");
        expect(inbox.texts.send).toBe("Enviar");
        expect(document.querySelector("chat-widget").texts.open).toBe(
            "Escríbenos",
        );
        const alone = document.querySelector("body > chat-thread");
        expect(alone.texts.send).toBe("Enviar");
        expect(alone.client).toBe(client);
        // The threads of an inbox or a widget are theirs.
        expect(inbox.querySelector("chat-thread").client).toBe(client);

        const later = document.createElement("chat-thread");
        attach(later);
        expect(later.client).toBe(client);
    });

    it("works without texts", async () => {
        vi.stubGlobal(
            "fetch",
            vi.fn(() => new Promise(() => {})),
        );
        page("<chat-thread></chat-thread>", { baseUrl: "", poll: 3000 });
        const { client } = await boot();
        expect(client.poll).toBe(3000);
        expect(document.querySelector("chat-thread").texts.send).toBe("Send");
    });

    it("says when it can't connect", async () => {
        vi.stubGlobal(
            "fetch",
            vi.fn(async () => ({
                ok: false,
                status: 403,
                json: async () => ({ errcode: "M_FORBIDDEN" }),
            })),
        );
        const error = vi.spyOn(console, "error").mockImplementation(() => {});
        page("", { baseUrl: "" });
        await boot();
        await new Promise((resolve) => setTimeout(resolve, 0));
        expect(error).toHaveBeenCalledWith(
            "django-chat-ui: can't connect.",
            expect.any(Error),
        );
    });

    it("does nothing without its configuration", async () => {
        page("<chat-thread></chat-thread>");
        const { client, config, attach } = await boot();
        expect([client, config]).toEqual([null, null]);
        attach(document.querySelector("chat-thread"));
        expect(document.querySelector("chat-thread").client).toBe(null);
        vi.resetModules();
        page("", "{nope");
        expect((await boot()).config).toBe(null);
    });
});
