import { afterEach, describe, expect, it, vi } from "vitest";
import {
    INBOX_TEXTS,
    preview,
} from "../../src/django_chat_ui/static/django_chat_ui/chat-inbox.js";
import {
    CARD,
    CONTACT,
} from "../../src/django_chat_ui/static/django_chat_ui/matrix.js";
import {
    ANA,
    BOT,
    flush,
    ME,
    says,
    setup,
    stopAll,
    text,
    withButtons,
} from "./helpers.js";

afterEach(() => {
    stopAll();
    document.body.replaceChildren();
});

const LUCY = { id: "@lucy:demo", kind: "user", name: "Lucy", handle: "lucy" };

const ROOMS = [
    [
        {
            id: "!wa:demo",
            channel: "whatsapp",
            members: [ME.id, ANA.id, BOT.id],
            unread: 2,
        },
        [{ sender: ANA.id, content: says("Hi"), ts: 2000 }],
    ],
    [
        {
            id: "!team:demo",
            channel: "internal",
            title: "Team",
            members: [ME.id, LUCY.id],
        },
        [{ sender: ME.id, content: says("Done"), ts: 3000 }],
    ],
    [{ id: "!bot:demo", channel: "bot", members: [ME.id, BOT.id] }, []],
];

async function inbox(rooms = ROOMS) {
    const { client, server } = await setup({ rooms, users: [ANA, BOT, LUCY] });
    const element = document.createElement("chat-inbox");
    document.body.append(element);
    element.client = client;
    await flush();
    return { inbox: element, client, server };
}

function items(element) {
    return [...element.querySelectorAll(".chat-conversation")];
}

describe("preview()", () => {
    const texts = { ...INBOX_TEXTS, deleted: "Deleted" };
    const of = (content, extra = {}) => preview({ content, ...extra }, texts);

    it("says what a message is about, in a line", () => {
        expect(preview(null, texts)).toBe("");
        expect(of({}, { redacted: true })).toBe("Deleted");
        expect(preview({ redacted: true }, INBOX_TEXTS)).toBe("");
        expect(of({ body: "a\n  b" })).toBe("a b");
        expect(of({})).toBe("");
        expect(
            of({
                body: "**Your** [order](https://x)\n- ships",
                markdown: true,
            }),
        ).toBe("Your order ships");
        expect(of({ markdown: true })).toBe("");
        expect(of(withButtons("Pick:", [{ id: "a", label: "A" }]))).toBe(
            "Pick:",
        );
        expect(of({ "io.github.rodolvbg.chat.buttons": {} })).toBe("");
        expect(of({ msgtype: "m.image" })).toBe("Photo");
        expect(of({ msgtype: "m.video" })).toBe("Video");
        expect(of({ msgtype: "m.audio" })).toBe("Audio");
        expect(of({ msgtype: "m.audio", "org.matrix.msc3245.voice": {} })).toBe(
            "Voice message",
        );
        expect(of({ msgtype: "m.location" })).toBe("Location");
        expect(
            of({ msgtype: "m.file", filename: "a.pdf", body: "Invoice" }),
        ).toBe("a.pdf");
        expect(of({ msgtype: "m.file", body: "Invoice" })).toBe("Invoice");
        expect(of({ msgtype: "m.file" })).toBe("");
        expect(
            of({ msgtype: CARD, body: "x", [CARD]: { title: "Shirt" } }),
        ).toBe("Shirt");
        expect(of({ msgtype: CARD, body: "x" })).toBe("x");
        expect(of({ msgtype: CARD })).toBe("");
        expect(of({ msgtype: CONTACT, [CONTACT]: { name: "Ana" } })).toBe(
            "Ana",
        );
        expect(of({ msgtype: CONTACT })).toBe("");
        expect(preview({}, texts)).toBe("");
    });
});

describe("<chat-inbox>", () => {
    it("lists the conversations, the latest active first", async () => {
        const { inbox: element } = await inbox();
        const [bot, team, wa] = items(element);
        expect(bot.dataset.conversation).toBe("!bot:demo"); // Created last.
        expect(team.querySelector(".chat-conversation-title").textContent).toBe(
            "Team",
        );
        expect(
            team.querySelector(".chat-conversation-preview").textContent,
        ).toBe("You: Done");
        expect(team.querySelector("time").dateTime).toBe(
            new Date(3000).toISOString(),
        );
        expect(wa.querySelector(".chat-conversation-title").textContent).toBe(
            "Ana García, Asistente",
        );
        expect(wa.querySelector(".chat-avatar").textContent).toBe("AG");
        expect(wa.dataset.channel).toBe("whatsapp");
        const badge = wa.querySelector(".chat-unread");
        expect(badge.textContent).toBe("2");
        expect(badge.getAttribute("aria-label")).toBe("2 unread");
        expect(bot.querySelector("time")).toBe(null);
        expect(element.querySelector(".chat-inbox-empty").hidden).toBe(true);
        expect(element.querySelector(".chat-inbox-pick").textContent).toBe(
            "Pick a conversation.",
        );
    });

    it("searches by title, names, handles and the last message", async () => {
        const { inbox: element } = await inbox();
        const search = element.querySelector(".chat-inbox-search");
        expect(search.placeholder).toBe("Search conversations");
        const find = (query) => {
            search.value = query;
            search.dispatchEvent(new Event("input"));
            return items(element).map((item) => item.dataset.conversation);
        };
        expect(find("TEAM")).toEqual(["!team:demo"]);
        expect(find("+34")).toEqual(["!wa:demo"]);
        expect(find("done")).toEqual(["!team:demo"]);
        expect(find("nothing")).toEqual([]);
        expect(element.querySelector(".chat-inbox-empty").textContent).toBe(
            "No conversation matches.",
        );
        expect(element.querySelector(".chat-inbox-empty").hidden).toBe(false);
        expect(find("  ")).toHaveLength(3);
    });

    it("opens one, says whom with, and goes back", async () => {
        const { inbox: element } = await inbox();
        const selected = vi.fn();
        element.addEventListener("select", (event) => selected(event.detail));
        items(element)
            .find((i) => i.dataset.conversation === "!wa:demo")
            .click();
        expect(selected).toHaveBeenCalledWith({ conversation: "!wa:demo" });
        expect(element.selected).toBe("!wa:demo");
        expect(
            element
                .querySelector(".chat-inbox")
                .classList.contains("chat-inbox--open"),
        ).toBe(true);
        expect(element.querySelector(".chat-inbox-title").textContent).toBe(
            "Ana García, Asistente",
        );
        expect(element.querySelector(".chat-inbox-subtitle").textContent).toBe(
            "whatsapp · +34 600 000 000",
        );
        const thread = element.querySelector("chat-thread");
        expect(thread.getAttribute("conversation")).toBe("!wa:demo");
        expect(document.activeElement).toBe(
            thread.querySelector(".chat-input"),
        );
        expect(
            element.querySelector('[aria-current="true"]').dataset.conversation,
        ).toBe("!wa:demo");
        await flush();
        // Opened: read.
        expect(
            items(element)
                .find((i) => i.dataset.conversation === "!wa:demo")
                .querySelector(".chat-unread"),
        ).toBe(null);

        element.selected = "!team:demo";
        expect(element.querySelector(".chat-inbox-subtitle").textContent).toBe(
            "internal · lucy",
        );
        element.querySelector(".chat-inbox-back").click();
        expect(element.selected).toBe(null);
        expect(thread.hasAttribute("conversation")).toBe(false);
        expect(element.querySelector(".chat-inbox-title").textContent).toBe("");
        expect(document.activeElement).toBe(items(element)[0]);
        element.selected = "!bot:demo";
        expect(element.querySelector(".chat-inbox-subtitle").textContent).toBe(
            "bot",
        );
    });

    it("updates as conversations come and go", async () => {
        const { inbox: element, server } = await inbox();
        server.post("!wa:demo", ANA.id, says("New"));
        await flush();
        expect(items(element)[0].dataset.conversation).toBe("!wa:demo");
        expect(
            text(items(element)[0].querySelector(".chat-conversation-preview")),
        ).toBe("New");
        server.leave("!team:demo", ME.id);
        await flush();
        expect(items(element)).toHaveLength(2);
    });

    it("says when there's nothing, in its texts", async () => {
        const { inbox: element } = await inbox([]);
        expect(element.querySelector(".chat-inbox-empty").textContent).toBe(
            "No conversations yet.",
        );
        element.texts = { empty: "Nada aún.", send: "Enviar" };
        expect(element.texts.empty).toBe("Nada aún.");
        expect(element.querySelector(".chat-inbox-empty").textContent).toBe(
            "Nada aún.",
        );
        expect(element.querySelector("chat-thread").texts.send).toBe("Enviar");
        expect(element.querySelector(".chat-inbox-back").title).toBe(
            "Back to conversations",
        );
    });

    it("can be set up before it's in the page, and let go", async () => {
        const { client } = await setup({ rooms: ROOMS });
        const element = document.createElement("chat-inbox");
        element.texts = { search: "Buscar" };
        element.selected = "!wa:demo";
        element.render();
        element.client = client;
        document.body.append(element);
        expect(
            element.querySelector("chat-thread").getAttribute("conversation"),
        ).toBe("!wa:demo");
        expect(element.querySelector(".chat-inbox-search").placeholder).toBe(
            "Buscar",
        );
        expect(element.client).toBe(client);
        element.remove();
        client.dispatchEvent(new Event("conversations")); // Not listened to.
        element.client = client;
        document.body.append(element); // Built once.
        expect(element.querySelectorAll(".chat-inbox")).toHaveLength(1);
        const blank = document.createElement("chat-inbox");
        document.body.append(blank);
        expect(items(blank)).toEqual([]);
        blank.selected = "!x";
        expect(blank.querySelector(".chat-inbox-title").textContent).toBe("");
    });

    it("names a conversation with nobody else, and without a title", async () => {
        const { inbox: element } = await inbox([
            [{ id: "!alone:demo", members: [ME.id] }, []],
        ]);
        const [alone] = items(element);
        expect(
            alone.querySelector(".chat-conversation-title").textContent,
        ).toBe("");
        expect(alone.querySelector(".chat-avatar").textContent).toBe("");
    });
});
