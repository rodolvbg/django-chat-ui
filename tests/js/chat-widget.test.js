import { afterEach, describe, expect, it, vi } from "vitest";
import "../../src/django_chat_ui/static/django_chat_ui/chat-widget.js";
import { WIDGET_TEXTS } from "../../src/django_chat_ui/static/django_chat_ui/chat-widget.js";
import { BOT, flush, ME, says, setup, stopAll } from "./helpers.js";

afterEach(() => {
    stopAll();
    document.body.replaceChildren();
    window.localStorage.clear();
    vi.restoreAllMocks();
});

async function widget(attributes = {}, rooms = []) {
    const { client, server } = await setup({ rooms });
    server.newRoom = { capabilities: { composer: { mode: "free" } } };
    server.onStart = (room) => {
        server.join(room, BOT.id);
        server.post(room, BOT.id, says("Hi! How can we help?"));
    };
    const element = document.createElement("chat-widget");
    for (const [name, value] of Object.entries(attributes)) {
        element.setAttribute(name, value);
    }
    document.body.append(element);
    element.client = client;
    await flush();
    return { widget: element, client, server };
}

describe("<chat-widget>", () => {
    it("opens, starting a conversation with the support team", async () => {
        const {
            widget: element,
            server,
            client,
        } = await widget({
            heading: "Support",
            subheading: "We answer in minutes",
            channel: "web",
            "storage-key": "support",
        });
        const launcher = element.querySelector(".chat-widget-launcher");
        expect(launcher.getAttribute("aria-label")).toBe("Chat with us");
        expect(launcher.getAttribute("aria-expanded")).toBe("false");
        expect(element.querySelector(".chat-widget-panel").hidden).toBe(true);
        const opened = vi.fn();
        element.addEventListener("open", (event) => opened(event.detail));
        launcher.click();
        await flush();
        expect(element.isOpen).toBe(true);
        expect(launcher.getAttribute("aria-label")).toBe("Close the chat");
        expect(element.querySelector(".chat-widget-heading").textContent).toBe(
            "Support",
        );
        expect(
            element.querySelector(".chat-widget-subheading").textContent,
        ).toBe("We answer in minutes");
        expect(
            element
                .querySelector(".chat-widget-panel")
                .getAttribute("aria-label"),
        ).toBe("Support");
        const created = server.received.find((r) =>
            r.path.endsWith("/createRoom"),
        );
        expect(created.body.invite).toEqual([]);
        expect(created.body.initial_state[0].content).toEqual({
            channel: "web",
        });
        const room = element.conversation;
        expect(opened).toHaveBeenCalledWith({ conversation: room });
        expect(
            window.localStorage.getItem("django-chat-ui:widget:support"),
        ).toBe(room);
        const thread = element.querySelector("chat-thread");
        expect(thread.getAttribute("conversation")).toBe(room);
        expect(thread.querySelector(".chat-message").textContent).toContain(
            "Hi! How can we help?",
        );
        expect(client.room(room).conversation.state).toBe("pending");

        // Closing (the button, Escape) and opening again: the same one.
        element.querySelector(".chat-widget-close").click();
        expect(element.isOpen).toBe(false);
        expect(document.activeElement).toBe(launcher);
        launcher.click();
        await flush();
        expect(
            server.received.filter((r) => r.path.endsWith("/createRoom")),
        ).toHaveLength(1);
        document.dispatchEvent(new KeyboardEvent("keydown", { key: "a" }));
        expect(element.isOpen).toBe(true);
        document.dispatchEvent(new KeyboardEvent("keydown", { key: "Escape" }));
        expect(element.isOpen).toBe(false);
        document.dispatchEvent(new KeyboardEvent("keydown", { key: "Escape" }));
    });

    it("counts what's unread while closed", async () => {
        const { widget: element, server } = await widget();
        element.open();
        await flush();
        element.close();
        const room = element.conversation;
        server.post(room, BOT.id, says("Still there?"));
        await flush();
        const badge = element.querySelector(".chat-widget-badge");
        expect(badge.hidden).toBe(false);
        // The greeting was seen while open; not what came after.
        expect(badge.textContent).toBe("1");
        expect(badge.getAttribute("aria-label")).toBe("1 unread");
        element.open();
        expect(badge.hidden).toBe(true);
        await flush();
        expect(server.rooms.get(room).unread).toBe(0);
    });

    it("starts one with someone, without remembering it", async () => {
        const { widget: element, server } = await widget({
            with: ` ${BOT.id}  `,
        });
        await element.open();
        const created = server.received.find((r) =>
            r.path.endsWith("/createRoom"),
        );
        expect(created.body.invite).toEqual([BOT.id]);
        expect(created.body.initial_state).toEqual([]);
        expect(window.localStorage.length).toBe(0);
    });

    it("shows the one it's given, or the one it remembers", async () => {
        const rooms = [
            [
                { id: "!given:demo", members: [ME.id] },
                [{ sender: ME.id, content: says("Before") }],
            ],
        ];
        const { widget: element, server } = await widget(
            { conversation: "!given:demo" },
            rooms,
        );
        await element.open();
        expect(
            element.querySelector("chat-thread").getAttribute("conversation"),
        ).toBe("!given:demo");
        expect(
            server.received.some((r) => r.path.endsWith("/createRoom")),
        ).toBe(false);

        window.localStorage.setItem(
            "django-chat-ui:widget:kept",
            "!given:demo",
        );
        const { widget: other } = await widget(
            { "storage-key": "kept" },
            rooms,
        );
        expect(other.conversation).toBe("!given:demo");
    });

    it("works without storage, and when it can't start one", async () => {
        vi.spyOn(Storage.prototype, "getItem").mockImplementation(() => {
            throw new Error("blocked");
        });
        vi.spyOn(Storage.prototype, "setItem").mockImplementation(() => {
            throw new Error("blocked");
        });
        const { widget: element, client } = await widget({
            "storage-key": "s",
        });
        expect(element.conversation).toBe(null);
        await element.open();
        expect(element.conversation).toMatch(/^!/);

        const { widget: failing, client: other } = await widget();
        vi.spyOn(other, "createRoom").mockRejectedValue(new Error("offline"));
        const opened = vi.fn();
        failing.addEventListener("open", opened);
        await failing.open();
        expect(opened).not.toHaveBeenCalled();
        expect(
            failing.querySelector("chat-thread").hasAttribute("conversation"),
        ).toBe(false);
        expect(client).not.toBe(other);
    });

    it("can have its client before it's in the page, and another later", async () => {
        const { client } = await setup();
        const { client: other } = await setup();
        const element = document.createElement("chat-widget");
        element.client = client;
        document.body.append(element);
        expect(element.querySelector("chat-thread").client).toBe(client);
        element.client = other;
        expect(element.querySelector("chat-thread").client).toBe(other);
        // The launcher closes it too.
        const launcher = element.querySelector(".chat-widget-launcher");
        launcher.click();
        await flush();
        launcher.click();
        expect(element.isOpen).toBe(false);
    });

    it("takes its texts and attributes, before or after it's in the page", async () => {
        const element = document.createElement("chat-widget");
        element.texts = { open: "Escríbenos", send: "Enviar" };
        element.setAttribute("heading", "Ayuda");
        element.open = element.open.bind(element);
        expect(element.texts.close).toBe(WIDGET_TEXTS.close);
        document.body.append(element);
        expect(
            element
                .querySelector(".chat-widget-launcher")
                .getAttribute("aria-label"),
        ).toBe("Escríbenos");
        expect(element.querySelector(".chat-widget-heading").textContent).toBe(
            "Ayuda",
        );
        expect(element.querySelector(".chat-widget-subheading").hidden).toBe(
            true,
        );
        element.setAttribute("heading", "Soporte");
        expect(element.querySelector(".chat-widget-heading").textContent).toBe(
            "Soporte",
        );
        element.texts = { heading: "Chat" };
        element.removeAttribute("heading");
        expect(element.querySelector(".chat-widget-heading").textContent).toBe(
            "Chat",
        );
        expect(element.querySelector("chat-thread").texts.heading).toBe("Chat");
        // Without a client: opens, and starts nothing.
        await element.open();
        expect(element.conversation).toBe(null);
        element.renderBadge();
        const { client } = await setup();
        element.client = client;
        expect(element.client).toBe(client);
        element.remove();
        client.dispatchEvent(new Event("conversations"));
        document.body.append(element);
        expect(element.querySelectorAll(".chat-widget-launcher")).toHaveLength(
            1,
        );
    });
});
