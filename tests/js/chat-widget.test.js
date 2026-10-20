import { afterEach, describe, expect, it, vi } from "vitest";
import { WIDGET_TEXTS } from "../../src/django_chat_ui/static/django_chat_ui/chat-widget.js";
import { flush, setup } from "./helpers.js";

async function widget(attributes = {}, options = {}) {
    const result = await setup(options);
    const element = document.createElement("chat-widget");
    for (const [name, value] of Object.entries(attributes)) element.setAttribute(name, value);
    document.body.append(element);
    element.client = result.client;
    await flush();
    return { ...result, widget: element };
}

const launcher = (element) => element.querySelector(".chat-widget-launcher");
const panel = (element) => element.querySelector(".chat-widget-panel");

afterEach(() => {
    document.body.replaceChildren();
    window.localStorage.clear();
});

describe("<chat-widget>", () => {
    it("is a button until opened", async () => {
        const { server, widget: element } = await widget({ heading: "Soporte", subheading: "Te respondemos en minutos" });

        expect(launcher(element).getAttribute("aria-expanded")).toBe("false");
        expect(launcher(element).getAttribute("aria-label")).toBe(WIDGET_TEXTS.open);
        expect(launcher(element).getAttribute("aria-controls")).toBe(panel(element).id);
        expect(panel(element).hidden).toBe(true);
        expect(panel(element).getAttribute("role")).toBe("dialog");
        expect(panel(element).getAttribute("aria-label")).toBe("Soporte");
        expect(element.querySelector(".chat-widget-subheading").textContent).toBe("Te respondemos en minutos");
        // Nothing started until someone opens it.
        expect(server.received.map((frame) => frame.type)).toEqual(["hello"]);
    });

    it("starts a conversation on opening, and shows it", async () => {
        const { server, client, widget: element } = await widget({ channel: "web", with: "p_support p_bot" });
        server.onStart = (conversation, s) => s.post(conversation.id, "p_bot", [{ type: "text", text: "¡Hola! ¿En qué te ayudo?" }]);
        const opened = vi.fn();
        element.addEventListener("open", (event) => opened(event.detail.conversation));

        launcher(element).click();
        await flush();

        const start = server.received.find((frame) => frame.data.with);
        expect(start.data).toEqual({ with: ["p_support", "p_bot"], channel: "web" });
        const id = element.conversation;
        expect(id).toMatch(/^conv_/);
        expect(opened).toHaveBeenCalledWith(id);
        expect(element.hasAttribute("open")).toBe(true);
        expect(launcher(element).getAttribute("aria-expanded")).toBe("true");
        expect(launcher(element).getAttribute("aria-label")).toBe(WIDGET_TEXTS.close);
        expect(panel(element).hidden).toBe(false);
        const thread = element.querySelector("chat-thread");
        expect(thread.getAttribute("conversation")).toBe(id);
        expect(client.conversation(id).messages.map((m) => m.parts[0].text)).toContain("¡Hola! ¿En qué te ayudo?");
        expect(document.activeElement).toBe(thread.querySelector(".chat-input"));

        // Opened again: the same one.
        element.close();
        launcher(element).click();
        await flush();
        expect(server.received.filter((frame) => frame.data.with)).toHaveLength(1);
    });

    it("closes with ×, Escape, or the button, giving the focus back", async () => {
        const { widget: element } = await widget();
        const closed = vi.fn();
        element.addEventListener("close", closed);

        for (const close of [
            () => element.querySelector(".chat-widget-close").click(),
            () => document.dispatchEvent(new KeyboardEvent("keydown", { key: "Escape" })),
            () => launcher(element).click(),
        ]) {
            await element.open();
            close();
            expect(element.hasAttribute("open")).toBe(false);
            expect(panel(element).hidden).toBe(true);
            expect(document.activeElement).toBe(launcher(element));
        }
        expect(closed).toHaveBeenCalledTimes(3);
        // Escape while closed does nothing.
        document.dispatchEvent(new KeyboardEvent("keydown", { key: "Escape" }));
        expect(closed).toHaveBeenCalledTimes(3);
    });

    it("shows a conversation it's given, with its unread count while closed", async () => {
        const conversation = { id: "conv_1", channel: "web", participants: [] };
        const { server, widget: element } = await widget({ conversation: "conv_1" }, { conversations: [[conversation, []]] });
        const badge = element.querySelector(".chat-widget-badge");
        expect(badge.hidden).toBe(true);

        server.post("conv_1", "p_agent", [{ type: "text", text: "¿Sigues ahí?" }]);
        await flush();
        expect(badge.hidden).toBe(false);
        expect(badge.textContent).toBe("1");
        expect(badge.getAttribute("aria-label")).toBe("1 unread");

        await element.open();
        expect(badge.hidden).toBe(true);
        expect(server.received.some((frame) => frame.data.with)).toBe(false);
        expect(element.querySelector("chat-thread").getAttribute("conversation")).toBe("conv_1");
    });

    it("remembers the conversation it started, with a storage key", async () => {
        const first = await widget({ "storage-key": "support" });
        await first.widget.open();
        const id = first.widget.conversation;
        expect(window.localStorage.getItem("django-chat-ui:widget:support")).toBe(id);
        document.body.replaceChildren();

        const second = await widget({ "storage-key": "support" });
        expect(second.widget.conversation).toBe(id);
    });

    it("works without storage", async () => {
        const getItem = vi.spyOn(Storage.prototype, "getItem").mockImplementation(() => {
            throw new Error("blocked");
        });
        const setItem = vi.spyOn(Storage.prototype, "setItem").mockImplementation(() => {
            throw new Error("blocked");
        });
        const { widget: element } = await widget({ "storage-key": "support" });
        await element.open();
        expect(element.conversation).toMatch(/^conv_/);
        getItem.mockRestore();
        setItem.mockRestore();
    });

    it("stays open, empty, if it can't start one", async () => {
        const { client, widget: element } = await widget();
        vi.spyOn(client, "start").mockRejectedValue(new Error("offline"));
        await element.open();
        expect(element.hasAttribute("open")).toBe(true);
        expect(element.conversation).toBeNull();
        expect(element.querySelector("chat-thread").hasAttribute("conversation")).toBe(false);
    });

    it("takes its texts", async () => {
        const { widget: element } = await widget();
        element.texts = { open: "Escríbenos", heading: "Ayuda" };
        expect(launcher(element).getAttribute("aria-label")).toBe("Escríbenos");
        expect(element.querySelector(".chat-widget-heading").textContent).toBe("Ayuda");
        expect(element.querySelector(".chat-widget-subheading").hidden).toBe(true);
        expect(element.texts.close).toBe(WIDGET_TEXTS.close);
        expect(element.client).toBeTruthy();
        element.setAttribute("heading", "Soporte");
        expect(element.querySelector(".chat-widget-heading").textContent).toBe("Soporte");
    });
});
