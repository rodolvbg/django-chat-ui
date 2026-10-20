import { afterEach, describe, expect, it, vi } from "vitest";
import {
    INBOX_TEXTS,
    preview,
} from "../../src/django_chat_ui/static/django_chat_ui/chat-inbox.js";
import { flush, ME, setup, text } from "./helpers.js";

const ANA = {
    id: "p_ana",
    kind: "contact",
    name: "Ana García",
    handle: "+34 600 000 000",
};
const BOT = { id: "p_bot", kind: "bot", name: "Bot" };
const at = (minute) => `2026-10-20T10:${String(minute).padStart(2, "0")}:00Z`;

const CONVERSATIONS = [
    [
        {
            id: "conv_wa",
            channel: "whatsapp",
            participants: [ME, ANA],
            unread: 2,
            updatedAt: at(5),
        },
        [
            {
                id: "w1",
                conversation: "conv_wa",
                author: "p_ana",
                createdAt: at(5),
                parts: [{ type: "text", text: "¿Tenéis la talla M?" }],
            },
        ],
    ],
    [
        {
            id: "conv_bot",
            channel: "bot",
            title: "Asistente",
            participants: [ME, BOT],
            updatedAt: at(1),
            lastMessage: {
                author: "p_me",
                createdAt: at(1),
                parts: [{ type: "image", url: "x.png" }],
            },
        },
        [],
    ],
];

async function inbox() {
    const result = await setup({ conversations: CONVERSATIONS });
    const element = document.createElement("chat-inbox");
    document.body.append(element);
    element.client = result.client;
    await flush();
    return { ...result, inbox: element };
}

const items = (element) => [...element.querySelectorAll(".chat-conversation")];

afterEach(() => {
    document.body.replaceChildren();
});

describe("<chat-inbox>", () => {
    it("lists the conversations, the latest active first", async () => {
        const { inbox: element } = await inbox();
        const [wa, bot] = items(element);

        expect(items(element).map((item) => item.dataset.conversation)).toEqual(
            ["conv_wa", "conv_bot"],
        );
        expect(wa.querySelector(".chat-conversation-title").textContent).toBe(
            "Ana García",
        );
        expect(wa.querySelector(".chat-avatar").textContent).toBe("AG");
        expect(wa.dataset.channel).toBe("whatsapp");
        expect(wa.querySelector(".chat-conversation-preview").textContent).toBe(
            "¿Tenéis la talla M?",
        );
        expect(
            wa.querySelector(".chat-unread").getAttribute("aria-label"),
        ).toBe("2 unread");
        expect(wa.querySelector("time").dateTime).toBe(at(5));
        // Its title, and what its last message is: the client's own photo.
        expect(bot.querySelector(".chat-conversation-title").textContent).toBe(
            "Asistente",
        );
        expect(
            bot.querySelector(".chat-conversation-preview").textContent,
        ).toBe("You: Photo");
        expect(bot.querySelector(".chat-unread")).toBeNull();
        expect(element.querySelector(".chat-inbox-empty").hidden).toBe(true);
        expect(element.querySelector(".chat-inbox-pick").hidden).toBe(false);
        expect(element.querySelector("chat-thread").hidden).toBe(true);
    });

    it("opens the one selected, and goes back", async () => {
        const { inbox: element } = await inbox();
        const select = vi.fn();
        element.addEventListener("select", (event) =>
            select(event.detail.conversation),
        );

        items(element)[0].click();
        await flush();

        expect(select).toHaveBeenCalledWith("conv_wa");
        expect(element.selected).toBe("conv_wa");
        expect(element.querySelector(".chat-inbox").classList).toContain(
            "chat-inbox--open",
        );
        expect(items(element)[0].getAttribute("aria-current")).toBe("true");
        const thread = element.querySelector("chat-thread");
        expect(thread.hidden).toBe(false);
        expect(thread.getAttribute("conversation")).toBe("conv_wa");
        expect(text(thread.querySelector(".chat-messages"))).toContain(
            "¿Tenéis la talla M?",
        );
        expect(document.activeElement).toBe(
            thread.querySelector(".chat-input"),
        );
        expect(element.querySelector(".chat-inbox-title").textContent).toBe(
            "Ana García",
        );
        expect(element.querySelector(".chat-inbox-subtitle").textContent).toBe(
            "whatsapp · +34 600 000 000",
        );

        element.querySelector(".chat-inbox-back").click();
        expect(select).toHaveBeenLastCalledWith(null);
        expect(element.selected).toBeNull();
        expect(thread.hasAttribute("conversation")).toBe(false);
        expect(thread.hidden).toBe(true);
        expect(document.activeElement).toBe(items(element)[0]);
    });

    it("moves a conversation up, with its count, when a message comes", async () => {
        const { server, inbox: element } = await inbox();
        server.post("conv_bot", "p_bot", [
            { type: "audio", url: "a.ogg", voice: true },
        ]);
        await flush();

        const [first] = items(element);
        expect(first.dataset.conversation).toBe("conv_bot");
        expect(
            first.querySelector(".chat-conversation-preview").textContent,
        ).toBe("Voice message");
        expect(first.querySelector(".chat-unread").textContent).toBe("1");
    });

    it("searches by title, name, handle and last message", async () => {
        const { inbox: element } = await inbox();
        const search = element.querySelector(".chat-inbox-search");
        const find = (query) => {
            search.value = query;
            search.dispatchEvent(new Event("input"));
            return items(element).map((item) => item.dataset.conversation);
        };

        expect(find("asist")).toEqual(["conv_bot"]);
        expect(find("+34 600")).toEqual(["conv_wa"]);
        expect(find("TALLA")).toEqual(["conv_wa"]);
        expect(find("nobody")).toEqual([]);
        expect(element.querySelector(".chat-inbox-empty").hidden).toBe(false);
        expect(element.querySelector(".chat-inbox-empty").textContent).toBe(
            INBOX_TEXTS.noResults,
        );
        expect(find(" ")).toHaveLength(2);
    });

    it("says when there are none, in its texts", async () => {
        const { client } = await setup();
        const element = document.createElement("chat-inbox");
        element.texts = { empty: "Nada todavía.", search: "Buscar" };
        document.body.append(element);
        element.client = client;

        expect(element.querySelector(".chat-inbox-empty").textContent).toBe(
            "Nada todavía.",
        );
        expect(element.querySelector(".chat-inbox-search").placeholder).toBe(
            "Buscar",
        );
        expect(element.texts.back).toBe(INBOX_TEXTS.back);
    });

    it("takes a selection made before it's on the page", async () => {
        const { client } = await setup({ conversations: CONVERSATIONS });
        const element = document.createElement("chat-inbox");
        element.selected = "conv_bot";
        element.client = client;
        document.body.append(element);
        await flush();

        expect(
            element.querySelector("chat-thread").getAttribute("conversation"),
        ).toBe("conv_bot");
        expect(element.querySelector(".chat-inbox-title").textContent).toBe(
            "Asistente",
        );
        expect(element.client).toBe(client);
        element.remove();
    });
});

describe("preview", () => {
    it("says what a message is", () => {
        const say = (part) => preview({ parts: [part] }, INBOX_TEXTS);
        expect(say({ type: "system", text: "Closed" })).toBe("Closed");
        expect(
            say({
                type: "text",
                format: "markdown",
                text: "Soy el **bot**: [mira](https://x.y)\n- `uno`",
            }),
        ).toBe("Soy el bot: mira uno");
        expect(say({ type: "text", format: "markdown" })).toBe("");
        expect(say({ type: "text" })).toBe("");
        expect(say({ type: "file", name: "a.pdf" })).toBe("a.pdf");
        expect(say({ type: "file", fallback: "A file" })).toBe("A file");
        expect(say({ type: "location" })).toBe("Location");
        expect(say({ type: "audio" })).toBe("Audio");
        expect(say({ type: "acme.order", fallback: "Order #1" })).toBe(
            "Order #1",
        );
        expect(say({ type: "acme.order" })).toBe("");
        expect(preview(null, INBOX_TEXTS)).toBe("");
        expect(preview({ parts: [] }, INBOX_TEXTS)).toBe("");
    });
});
