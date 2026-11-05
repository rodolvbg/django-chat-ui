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
    window.history.replaceState(null, "", "/");
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

describe("<chat-inbox> in the URL", () => {
    const pick = (element, id) =>
        element.querySelector(`[data-conversation="${id}"]`).click();
    const param = () =>
        new URLSearchParams(window.location.search).get("conversation");

    it("writes the conversation open, and opens the URL's", async () => {
        window.history.replaceState(null, "", "/inbox/?tab=1");
        const { inbox: element } = await inbox();
        expect(element.selected).toBe(null);
        pick(element, "!wa:demo");
        // Its room ID's, without the "!" and our own server.
        expect(param()).toBe("wa");
        expect(window.location.search).toBe("?tab=1&conversation=wa");
        const length = window.history.length;
        pick(element, "!wa:demo"); // The same: no new entry.
        expect(window.history.length).toBe(length);
        element.querySelector(".chat-inbox-back").click();
        expect(window.location.search).toBe("?tab=1");

        // A reload, or a link: opened.
        window.history.replaceState(null, "", "/inbox/?conversation=team");
        const { inbox: again } = await inbox();
        expect(again.selected).toBe("!team:demo");
        expect(again.querySelector(".chat-inbox-title").textContent).toBe(
            "Team",
        );
        // An old link, by its room ID: opened, and its key in the URL.
        document.body.replaceChildren();
        window.history.replaceState(null, "", "/?conversation=!bot:demo");
        const length2 = window.history.length;
        const { inbox: old } = await inbox();
        expect(old.selected).toBe("!bot:demo");
        expect(param()).toBe("bot");
        expect(window.history.length).toBe(length2);
    });

    it("follows back and forward", async () => {
        const { inbox: element } = await inbox();
        const selects = [];
        element.addEventListener("select", (event) =>
            selects.push(event.detail.conversation),
        );
        window.history.pushState(null, "", "/?conversation=team");
        window.dispatchEvent(new PopStateEvent("popstate"));
        expect(element.selected).toBe("!team:demo");
        window.dispatchEvent(new PopStateEvent("popstate")); // Still it.
        window.history.pushState(null, "", "/");
        window.dispatchEvent(new PopStateEvent("popstate"));
        expect(element.selected).toBe(null);
        expect(selects).toEqual(["!team:demo", null]);
        // Let go: no longer.
        element.remove();
        window.history.pushState(null, "", "/?conversation=!team:demo");
        window.dispatchEvent(new PopStateEvent("popstate"));
        expect(element.selected).toBe(null);
    });

    it("its own parameter's name, or not in the URL", async () => {
        const { client } = await setup({
            rooms: ROOMS,
            users: [ANA, BOT, LUCY],
        });
        const named = document.createElement("chat-inbox");
        named.setAttribute("url-param", "chat");
        named.client = client;
        named.selected = "!bot:demo"; // Before: the URL names none.
        document.body.append(named);
        await flush();
        expect(named.selected).toBe("!bot:demo");
        expect(named.thread.getAttribute("conversation")).toBe("!bot:demo");
        pick(named, "!wa:demo");
        expect(window.location.search).toBe("?chat=wa");

        window.history.replaceState(null, "", "/?conversation=!team:demo");
        for (const off of ["off", "false"]) {
            const element = document.createElement("chat-inbox");
            element.setAttribute("url-state", off);
            element.client = client;
            document.body.append(element);
            await flush();
            expect(element.selected).toBe(null);
            pick(element, "!bot:demo");
            expect(window.location.search).toBe("?conversation=!team:demo");
            window.dispatchEvent(new PopStateEvent("popstate"));
            expect(element.selected).toBe("!bot:demo");
            element.remove();
        }
    });

    async function keyed(attrs = {}, rooms = ROOMS, before) {
        const { client, server } = await setup({
            rooms,
            users: [ANA, BOT, LUCY],
        });
        const element = document.createElement("chat-inbox");
        for (const [name, value] of Object.entries(attrs)) {
            element.setAttribute(name, value);
        }
        before?.(element);
        document.body.append(element);
        element.client = client;
        await flush();
        return { element, client, server };
    }

    it("named by its room ID, its contact's handle or its ext", async () => {
        let { element } = await keyed({ "url-key": "id" });
        pick(element, "!wa:demo");
        expect(window.location.search).toBe("?conversation=%21wa%3Ademo");
        element.remove();

        ({ element } = await keyed({ "url-key": "handle" }));
        pick(element, "!wa:demo"); // Ana's, not the bot's.
        expect(param()).toBe("+34 600 000 000");
        pick(element, "!team:demo");
        expect(param()).toBe("lucy");
        pick(element, "!bot:demo"); // None: its room ID.
        expect(param()).toBe("!bot:demo");
        element.remove();
        window.history.replaceState(
            null,
            "",
            `/?conversation=${encodeURIComponent("+34 600 000 000")}`,
        );
        ({ element } = await keyed({ "url-key": "handle" }));
        expect(element.selected).toBe("!wa:demo");
        element.remove();

        const rooms = [
            [
                {
                    id: "!p:demo",
                    members: [ME.id],
                    ext: { patient: { id: 7 } },
                },
                [],
            ],
            [{ id: "!q:demo", members: [ME.id], ext: { patient: {} } }, []],
            [{ id: "!r:demo", members: [ME.id] }, []],
        ];
        ({ element } = await keyed({ "url-key": "ext.patient.id" }, rooms));
        pick(element, "!p:demo");
        expect(param()).toBe("7");
        pick(element, "!q:demo");
        expect(param()).toBe("!q:demo");
        pick(element, "!r:demo");
        expect(param()).toBe("!r:demo");
        element.remove();
        window.history.replaceState(null, "", "/?conversation=7");
        ({ element } = await keyed({ "url-key": "ext.patient.id" }, rooms));
        expect(element.selected).toBe("!p:demo");
    });

    it("another server's room, or an unknown url-key: its room ID", async () => {
        const rooms = [[{ id: "!x:other", members: [ME.id] }, []]];
        let { element } = await keyed({}, rooms);
        pick(element, "!x:other");
        expect(param()).toBe("!x:other");
        element.remove();
        ({ element } = await keyed({ "url-key": "nope" }));
        pick(element, "!wa:demo");
        expect(param()).toBe("!wa:demo");
        element.select("!unknown:demo"); // None it has: as it is.
        expect(param()).toBe("!unknown:demo");
        element.remove();
        const lone = document.createElement("chat-inbox"); // No client yet.
        document.body.append(lone);
        lone.select("!wa:demo");
        expect(param()).toBe("!wa:demo");
    });

    it("its own urlKey, the latest of those with the key", async () => {
        const rooms = [
            ...ROOMS,
            [
                {
                    id: "!sms:demo",
                    channel: "sms",
                    members: [ME.id, ANA.id],
                },
                [{ sender: ANA.id, content: says("Again"), ts: 5000 }],
            ],
        ];
        const urlKey = vi.fn((conversation, me) => {
            expect(me).toBe(ME.id);
            return conversation.channel === "bot"
                ? null
                : conversation.participants.find((p) => p.id === ANA.id)
                      ?.handle;
        });
        let { element } = await keyed({ "url-key": "id" }, rooms, (e) => {
            e.urlKey = urlKey;
        });
        pick(element, "!wa:demo");
        expect(param()).toBe("+34 600 000 000");
        pick(element, "!bot:demo");
        expect(param()).toBe("!bot:demo");
        element.remove();
        // Two with Ana: the latest active.
        window.history.replaceState(
            null,
            "",
            `/?conversation=${encodeURIComponent("+34 600 000 000")}`,
        );
        ({ element } = await keyed({}, rooms, (e) => {
            e.urlKey = urlKey;
        }));
        expect(element.selected).toBe("!sms:demo");
    });

    it("waits for the conversation it names", async () => {
        window.history.replaceState(null, "", "/?conversation=late");
        const { element, server } = await keyed();
        expect(element.selected).toBe(null);
        const selects = [];
        element.addEventListener("select", (event) =>
            selects.push(event.detail.conversation),
        );
        // Back to a key none has yet: once it's there, announced.
        window.history.pushState(null, "", "/?conversation=later");
        window.dispatchEvent(new PopStateEvent("popstate"));
        expect(element.selected).toBe(null);
        server.addRoom({ id: "!later:demo", members: [ME.id] });
        await flush(60);
        expect(element.selected).toBe("!later:demo");
        expect(selects).toEqual(["!later:demo"]);
        // Picked meanwhile: the pick.
        window.history.pushState(null, "", "/?conversation=never");
        window.dispatchEvent(new PopStateEvent("popstate"));
        pick(element, "!wa:demo");
        expect(element.selected).toBe("!wa:demo");
        expect(param()).toBe("wa");
    });

    it("a key none has: resolveUrlKey's room", async () => {
        window.history.replaceState(null, "", "/?conversation=12345");
        const resolveUrlKey = vi.fn(async (key) =>
            key === "12345" ? "!team:demo" : null,
        );
        const { element } = await keyed({}, ROOMS, (e) => {
            e.resolveUrlKey = resolveUrlKey;
        });
        expect(resolveUrlKey).toHaveBeenCalledExactlyOnceWith("12345");
        expect(element.selected).toBe("!team:demo");
        expect(param()).toBe("12345"); // As it was linked.

        // Back to one it doesn't know: none, asked once.
        const selects = [];
        element.addEventListener("select", (event) =>
            selects.push(event.detail.conversation),
        );
        window.history.pushState(null, "", "/?conversation=x");
        window.dispatchEvent(new PopStateEvent("popstate"));
        window.dispatchEvent(new PopStateEvent("popstate"));
        await flush();
        expect(resolveUrlKey).toHaveBeenCalledTimes(2);
        expect(element.selected).toBe("!team:demo");
        // Back to one it knows, while asked: that one.
        window.history.pushState(null, "", "/?conversation=12345");
        window.dispatchEvent(new PopStateEvent("popstate"));
        window.history.pushState(null, "", "/?conversation=wa");
        window.dispatchEvent(new PopStateEvent("popstate"));
        await flush();
        expect(element.selected).toBe("!wa:demo");
        expect(selects).toEqual(["!wa:demo"]);
        element.remove();

        // Its conversations there before it's asked: one of them.
        let release;
        const { client } = await setup({
            rooms: ROOMS,
            users: [ANA, BOT, LUCY],
        });
        const slow = document.createElement("chat-inbox");
        slow.resolveUrlKey = resolveUrlKey;
        client.ready = new Promise((resolve) => {
            release = resolve;
        });
        window.history.replaceState(null, "", "/?conversation=nobody");
        document.body.append(slow);
        slow.client = client;
        window.history.replaceState(null, "", "/?conversation=bot");
        slow.fromUrl(true);
        release();
        await flush();
        expect(slow.selected).toBe("!bot:demo");
        expect(resolveUrlKey).toHaveBeenCalledTimes(2);
    });
});
