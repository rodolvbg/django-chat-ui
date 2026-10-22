import { afterEach, describe, expect, it, vi } from "vitest";
import { TEXTS } from "../../src/django_chat_ui/static/django_chat_ui/chat-thread.js";
import {
    registerMsgtype,
    unregisterMsgtype,
} from "../../src/django_chat_ui/static/django_chat_ui/content.js";
import {
    ACTION,
    DELIVERED,
    STATUS,
    SYSTEM,
    TEMPLATE,
} from "../../src/django_chat_ui/static/django_chat_ui/matrix.js";
import {
    ANA,
    BOT,
    flush,
    ME,
    messages,
    says,
    setup,
    stopAll,
    text,
    withButtons,
} from "./helpers.js";

const bot = {
    id: "!bot:demo",
    channel: "bot",
    members: [ME.id, BOT.id],
    capabilities: { buttons: true, composer: { mode: "free" } },
};

const whatsapp = {
    id: "!wa:demo",
    channel: "whatsapp",
    members: [ME.id, ANA.id],
    capabilities: {
        receipts: true,
        typing: true,
        reactions: true,
        composer: { mode: "free", placeholder: "Write to Ana", maxLength: 10 },
    },
};

function type(thread, value) {
    const input = thread.querySelector(".chat-input");
    input.value = value;
    input.dispatchEvent(new Event("input"));
    return input;
}

function enter(input, options = {}) {
    input.dispatchEvent(
        new KeyboardEvent("keydown", {
            key: "Enter",
            bubbles: true,
            cancelable: true,
            ...options,
        }),
    );
}

function sentBodies(server) {
    return server.received
        .filter(
            (r) =>
                r.method === "PUT" && r.path.includes("/send/m.room.message/"),
        )
        .map((r) => r.body.body);
}

afterEach(() => {
    stopAll();
    document.body.replaceChildren();
    vi.useRealTimers();
    vi.restoreAllMocks();
});

describe("<chat-thread>", () => {
    it("shows the messages, who wrote them, and how they're grouped", async () => {
        const { thread } = await setup({
            rooms: [
                [
                    whatsapp,
                    [
                        { sender: ANA.id, content: says("Hi") },
                        { sender: ANA.id, content: says("Are you there?") },
                        { sender: ME.id, content: says("Yes") },
                        {
                            sender: "@system:demo",
                            content: {
                                msgtype: "m.notice",
                                body: "Ana joined",
                                [SYSTEM]: {},
                            },
                        },
                        { sender: "@ghost:demo", content: says("Boo") },
                    ],
                ],
            ],
            thread: "!wa:demo",
        });
        const [hi, again, yes, joined, ghost] = messages(thread);
        expect(hi.className).toBe("chat-message chat-message--contact");
        expect(hi.querySelector(".chat-author").textContent).toBe("Ana García");
        expect(again.classList.contains("chat-message--continued")).toBe(true);
        expect(again.querySelector(".chat-author")).toBe(null);
        expect(yes.className).toBe("chat-message chat-message--own");
        expect(yes.querySelector(".chat-author")).toBe(null);
        expect(joined.className).toBe("chat-message chat-message--system");
        expect(joined.querySelector(".chat-system").textContent).toBe(
            "Ana joined",
        );
        expect(joined.querySelector(".chat-meta")).toBe(null);
        // Someone it doesn't know: a contact, without a name.
        expect(ghost.className).toBe("chat-message chat-message--contact");
        expect(ghost.querySelector(".chat-author")).toBe(null);
        expect(hi.querySelector("time").dateTime).toMatch(/Z$/);
        expect(
            thread.querySelector(".chat-log").getAttribute("aria-label"),
        ).toBe("Messages");
    });

    it("shows the server's and system participants' notices as such", async () => {
        const { thread, server } = await setup({
            rooms: [[{ id: "!r:demo", members: [ME.id, "@sys:demo"] }, []]],
            users: [{ id: "@sys:demo", kind: "system", name: "System" }],
            thread: "!r:demo",
        });
        server.post("!r:demo", "@sys:demo", says("Assigned"));
        server.post("!r:demo", "@system:demo", says("Closed"));
        await flush();
        expect(messages(thread).map((m) => m.className)).toEqual([
            "chat-message chat-message--system",
            "chat-message chat-message--system",
        ]);
    });

    it("sends what's written, on Enter or Send", async () => {
        const { thread, server } = await setup({
            rooms: [[whatsapp, []]],
            thread: "!wa:demo",
        });
        const input = type(thread, "  Hello  ");
        expect(input.placeholder).toBe("Write to Ana");
        expect(input.getAttribute("aria-label")).toBe("Write to Ana");
        expect(input.maxLength).toBe(10);
        enter(input, { shiftKey: true }); // A new line, not sent.
        enter(input, { isComposing: true });
        enter(input);
        expect(input.value).toBe("");
        type(thread, "Again");
        thread.querySelector(".chat-send").click();
        type(thread, "   ");
        enter(input);
        input.dispatchEvent(new KeyboardEvent("keydown", { key: "a" }));
        await flush();
        expect(sentBodies(server)).toEqual(["Hello", "Again"]);
        expect(messages(thread).map(text)).toEqual([
            expect.stringContaining("Hello"),
            expect.stringContaining("Again"),
        ]);
    });

    it("says who is typing, and that it is", async () => {
        const { thread, server } = await setup({
            rooms: [[whatsapp, []]],
            thread: "!wa:demo",
        });
        server.typing("!wa:demo", ANA.id, true);
        await flush();
        expect(thread.querySelector(".chat-typing").textContent).toBe(
            "Ana García is typing…",
        );
        server.addUser({ id: "@x:demo", name: "X" });
        server.typing("!wa:demo", "@x:demo", true);
        server.typing("!wa:demo", ME.id, true);
        await flush();
        expect(thread.querySelector(".chat-typing").textContent).toBe(
            "Several people are typing…",
        );
        server.typing("!wa:demo", ANA.id, false);
        server.typing("!wa:demo", "@x:demo", false);
        await flush();
        expect(thread.querySelector(".chat-typing").textContent).toBe("");
        server.typing("!wa:demo", "@nobody:demo", true);
        await flush();
        expect(thread.querySelector(".chat-typing").textContent).toBe(
            " is typing…",
        );

        // Its own: once while typing, stopped after 3 s or on sending.
        const timers = vi.spyOn(globalThis, "setTimeout");
        type(thread, "a");
        type(thread, "ab");
        const typing = () =>
            server.received
                .filter(
                    (r) => r.path.includes("/typing/") && r.method === "PUT",
                )
                .map((r) => r.body.typing);
        await flush();
        expect(typing()).toEqual([true]);
        const stop = timers.mock.calls
            .filter(([, delay]) => delay === 3000)
            .at(-1)[0];
        timers.mockRestore();
        stop();
        await flush();
        expect(typing()).toEqual([true, false]);
        type(thread, "abc");
        enter(thread.querySelector(".chat-input"));
        await flush();
        expect(typing()).toEqual([true, false, true, false]);
        thread.stopTyping(); // Stopped already: nothing.
        await flush();
        expect(typing()).toHaveLength(4);
    });

    it("doesn't say it types where the conversation doesn't show it", async () => {
        const { thread, server } = await setup({
            rooms: [[bot, []]],
            thread: "!bot:demo",
        });
        type(thread, "a");
        await flush();
        expect(server.received.some((r) => r.path.includes("/typing/"))).toBe(
            false,
        );
    });

    it("shows how far its messages got, with receipts", async () => {
        const { thread, server, client } = await setup({
            rooms: [[whatsapp, []]],
            thread: "!wa:demo",
        });
        type(thread, "Hi");
        enter(thread.querySelector(".chat-input"));
        const sending = messages(thread)[0].querySelector(".chat-status");
        expect(sending.className).toBe("chat-status chat-status--sending");
        expect(sending.textContent).toBe("🕓");
        await flush();
        const id = client.room("!wa:demo").messages[0].id;
        expect(
            messages(thread)[0].querySelector(".chat-status").textContent,
        ).toBe("✓");
        server.receipt("!wa:demo", ANA.id, id, DELIVERED);
        await flush();
        expect(messages(thread)[0].querySelector(".chat-status").title).toBe(
            "Delivered",
        );
        server.receipt("!wa:demo", ANA.id, id);
        await flush();
        const read = messages(thread)[0].querySelector(".chat-status");
        expect([
            read.className,
            read.textContent,
            read.getAttribute("aria-label"),
        ]).toEqual(["chat-status chat-status--read", "✓✓", "Read"]);
        // A status of its own, without a text for it.
        client.room("!wa:demo").applySync({
            ephemeral: {
                events: [
                    {
                        type: STATUS,
                        content: { event_id: id, status: "queued" },
                    },
                ],
            },
        });
        expect(messages(thread)[0].dataset.status).toBe("read");
    });

    it("shows what failed, and sends it again", async () => {
        const { thread, server } = await setup({
            rooms: [[bot, []]],
            thread: "!bot:demo",
        });
        server.reject = () => ({ errcode: "M_FORBIDDEN", error: "Blocked." });
        type(thread, "Hi");
        enter(thread.querySelector(".chat-input"));
        await flush();
        const [failed] = messages(thread);
        expect(failed.dataset.status).toBe("failed");
        expect(failed.querySelector(".chat-status--failed").textContent).toBe(
            "Blocked.",
        );
        // Without receipts, the others' statuses aren't shown.
        server.reject = null;
        failed.querySelector(".chat-retry").click();
        await flush();
        expect(messages(thread)[0].querySelector(".chat-status")).toBe(null);
        expect(sentBodies(server)).toEqual(["Hi", "Hi"]);
        // Failing again: still offered.
        server.reject = () => ({ errcode: "M_FORBIDDEN" });
        type(thread, "Again");
        enter(thread.querySelector(".chat-input"));
        await flush();
        const second = messages(thread)[1];
        expect(second.querySelector(".chat-status--failed").textContent).toBe(
            "M_FORBIDDEN",
        );
        second.querySelector(".chat-retry").click();
        await flush();
        expect(messages(thread)[1].dataset.status).toBe("failed");
        // A failure without a message: "Not sent".
        const store = thread.store;
        store.events.at(-1).error = undefined;
        store.changed();
        expect(
            messages(thread)[1].querySelector(".chat-status--failed")
                .textContent,
        ).toBe("Not sent");
    });

    it("shows edits and deletions", async () => {
        const { thread, server, client } = await setup({
            rooms: [[whatsapp, [{ sender: ANA.id, content: says("Hi") }]]],
            thread: "!wa:demo",
        });
        const id = client.room("!wa:demo").messages[0].id;
        server.post("!wa:demo", ANA.id, {
            msgtype: "m.text",
            body: "* Hello",
            "m.new_content": says("Hello"),
            "m.relates_to": { rel_type: "m.replace", event_id: id },
        });
        await flush();
        const [edited] = messages(thread);
        expect(edited.querySelector(".chat-text").textContent).toBe("Hello");
        expect(edited.querySelector(".chat-edited").textContent).toBe("edited");
        server.redact("!wa:demo", id, ANA.id);
        await flush();
        const [deleted] = messages(thread);
        expect(deleted.querySelector(".chat-deleted").textContent).toBe(
            "Message deleted",
        );
        expect(deleted.querySelector(".chat-react")).toBe(null);
    });

    it("tells the server what was read, once, and again if it failed", async () => {
        const { thread, server, client } = await setup({
            rooms: [
                [
                    { ...whatsapp, unread: 1 },
                    [{ sender: ANA.id, content: says("Hi") }],
                ],
            ],
            thread: "!wa:demo",
        });
        const reads = () =>
            server.received.filter((r) => r.path.includes("/receipt/m.read/"));
        expect(reads()).toHaveLength(1);
        thread.render();
        expect(reads()).toHaveLength(1);
        await flush();
        expect(client.room("!wa:demo").unread).toBe(0);

        // Hidden: not read.
        Object.defineProperty(document, "hidden", {
            configurable: true,
            value: true,
        });
        server.post("!wa:demo", ANA.id, says("Hello?"));
        await flush();
        expect(reads()).toHaveLength(1);
        Object.defineProperty(document, "hidden", {
            configurable: true,
            value: false,
        });

        // A failure: told again on the next render.
        vi.spyOn(client, "read").mockRejectedValueOnce(new Error("offline"));
        thread.render();
        await flush();
        expect(thread.readSent).toBe(null);
        thread.render();
        await flush();
        expect(reads()).toHaveLength(2);
        // Its own messages aren't "read".
        type(thread, "Bye");
        enter(thread.querySelector(".chat-input"));
        await flush();
        expect(reads()).toHaveLength(2);
    });

    it("keeps an older failure from undoing a newer read", async () => {
        const { thread, client } = await setup({
            rooms: [[whatsapp, [{ sender: ANA.id, content: says("Hi") }]]],
            thread: "!wa:demo",
        });
        let fail;
        vi.spyOn(client, "read").mockImplementation(
            () =>
                new Promise((_, reject) => {
                    fail = reject;
                }),
        );
        thread.readSent = null;
        thread.markRead();
        thread.readSent = "$other";
        fail(new Error("x"));
        await flush();
        expect(thread.readSent).toBe("$other");
    });

    it("loads earlier messages where there's history", async () => {
        const history = Array.from({ length: 6 }, (_, n) => ({
            sender: ANA.id,
            content: says(String(n)),
        }));
        const { thread } = await setup({
            rooms: [
                [
                    {
                        ...whatsapp,
                        capabilities: {
                            ...whatsapp.capabilities,
                            history: true,
                        },
                    },
                    history,
                ],
            ],
            thread: "!wa:demo",
            options: { limit: 3 },
        });
        const earlier = thread.querySelector(".chat-earlier");
        expect(earlier.hidden).toBe(false);
        expect(earlier.textContent).toBe("Load earlier messages");
        earlier.click();
        await flush();
        const bodies = messages(thread).map(
            (m) => m.querySelector(".chat-text").textContent,
        );
        expect(bodies).toEqual(["0", "1", "2", "3", "4", "5"]);
        await thread.loadEarlier(); // Nothing older.
        expect(thread.querySelector(".chat-earlier").hidden).toBe(true);
    });

    it("hides the earlier messages button without history", async () => {
        const { thread } = await setup({
            rooms: [[whatsapp, []]],
            thread: "!wa:demo",
        });
        expect(thread.querySelector(".chat-earlier").hidden).toBe(true);
    });

    it("keeps an earlier messages failure quiet", async () => {
        const { thread, client } = await setup({
            rooms: [[whatsapp, []]],
            thread: "!wa:demo",
        });
        vi.spyOn(client, "history").mockRejectedValue(new Error("x"));
        await thread.loadEarlier();
    });

    it("uses quick replies: their label as the answer", async () => {
        const { thread, server } = await setup({
            rooms: [
                [
                    bot,
                    [
                        {
                            sender: BOT.id,
                            content: withButtons("How can I help?", [
                                { id: "order", label: "My order" },
                            ]),
                        },
                    ],
                ],
            ],
            thread: "!bot:demo",
        });
        const pressed = vi.fn();
        server.onAction = (_event, _server, button) => pressed(button);
        thread.querySelector(".chat-button").click();
        // At once: answered, so the buttons are done.
        expect(
            messages(thread).at(-1).querySelector(".chat-text").textContent,
        ).toBe("My order");
        expect(thread.querySelector(".chat-button").disabled).toBe(true);
        await flush();
        expect(pressed).toHaveBeenCalledWith({
            id: "order",
            label: "My order",
        });
        const sent = server.received.find((r) => r.body?.[ACTION]);
        expect(sent.body[ACTION].button).toBe("order");
    });

    it("keeps a failed button quiet", async () => {
        const { thread, server } = await setup({
            rooms: [
                [
                    bot,
                    [
                        {
                            sender: BOT.id,
                            content: withButtons("?", [
                                { id: "a", label: "A" },
                            ]),
                        },
                    ],
                ],
            ],
            thread: "!bot:demo",
        });
        server.reject = () => ({ errcode: "M_FORBIDDEN" });
        thread.querySelector(".chat-button").click();
        await flush();
        expect(messages(thread).at(-1).dataset.status).toBe("failed");
    });

    it("shows a bot's answer as it's written", async () => {
        const { thread, server } = await setup({
            rooms: [[bot, []]],
            thread: "!bot:demo",
        });
        server.typing("!bot:demo", BOT.id, true);
        const done = server.stream("!bot:demo", BOT.id, [
            "Your order ",
            "**ships**",
        ]);
        await flush(3);
        const writing = messages(thread).at(-1);
        expect(writing.classList.contains("chat-message--streaming")).toBe(
            true,
        );
        expect(writing.querySelector(".chat-time")).toBe(null);
        expect(writing.querySelector(".chat-react")).toBe(null);
        // Who writes a message that shows isn't "typing".
        expect(thread.querySelector(".chat-typing").textContent).toBe("");
        await done;
        await flush();
        const [answer] = messages(thread);
        expect(answer.classList.contains("chat-message--streaming")).toBe(
            false,
        );
        expect(answer.textContent).toContain("Your order");
    });

    it("follows the composer's mode", async () => {
        const templates = [
            {
                id: "hi",
                name: "Hello",
                preview: "Hi {{1}}, {{2}}{{3}} {{name}}",
                params: ["name", "day"],
            },
            { id: "bye", preview: "Bye" },
            { id: "blank" },
        ];
        const { thread, server } = await setup({
            rooms: [[whatsapp, []]],
            thread: "!wa:demo",
        });
        const composer = thread.querySelector(".chat-composer");
        expect(composer.dataset.mode).toBe("free");

        server.setCapabilities("!wa:demo", {
            composer: {
                mode: "templates",
                reason: "24 hours passed.",
                templates,
            },
        });
        await flush();
        expect(composer.dataset.mode).toBe("templates");
        expect(composer.querySelector(".chat-composer-note").textContent).toBe(
            "24 hours passed.",
        );
        const select = composer.querySelector(".chat-template");
        expect([...select.options].map((o) => o.textContent)).toEqual([
            "Hello",
            "bye",
            "blank",
        ]);
        const [name, day] = composer.querySelectorAll(".chat-template-param");
        expect(name.placeholder).toBe("name");
        name.value = "Ana";
        name.dispatchEvent(new Event("input"));
        expect(
            composer.querySelector(".chat-template-preview").textContent,
        ).toBe("Hi Ana, {{2}}{{3}} Ana");
        day.value = "Monday";
        day.dispatchEvent(new Event("input"));
        composer.querySelector(".chat-send").click();
        await flush();
        const sent = server.received.find((r) => r.body?.msgtype === TEMPLATE);
        expect(sent.body).toEqual({
            msgtype: TEMPLATE,
            body: "Hi Ana, Monday{{3}} Ana",
            [TEMPLATE]: { id: "hi", params: { name: "Ana", day: "Monday" } },
        });
        select.value = "bye";
        select.dispatchEvent(new Event("change"));
        expect(
            composer.querySelector(".chat-template-preview").textContent,
        ).toBe("Bye");
        expect(composer.querySelectorAll(".chat-template-param")).toHaveLength(
            0,
        );
        select.value = "blank";
        select.dispatchEvent(new Event("change"));
        expect(
            composer.querySelector(".chat-template-preview").textContent,
        ).toBe("");
        select.value = "";
        select.dispatchEvent(new Event("change"));
        expect(
            composer.querySelector(".chat-template-preview").textContent,
        ).toBe("");
        thread.submit(); // No template chosen: nothing.

        server.setCapabilities("!wa:demo", { composer: { mode: "templates" } });
        await flush();
        expect(composer.querySelector(".chat-composer-note")).toBe(null);
        expect(composer.querySelector(".chat-template").options).toHaveLength(
            0,
        );
        thread.submit(); // None to send.

        server.setCapabilities("!wa:demo", { composer: { mode: "actions" } });
        await flush();
        expect(composer.textContent).toBe("Choose one of the options above.");
        thread.submit();
        server.setCapabilities("!wa:demo", {
            composer: { mode: "closed", reason: "Done." },
        });
        await flush();
        expect(composer.textContent).toBe("Done.");
        server.setCapabilities("!wa:demo", {
            composer: { mode: "com.acme.voice" },
        });
        await flush();
        expect(composer.textContent).toBe("This conversation is closed.");
    });

    it("keeps what's being written while the conversation changes", async () => {
        const { thread, server } = await setup({
            rooms: [[whatsapp, []]],
            thread: "!wa:demo",
        });
        type(thread, "Half");
        server.post("!wa:demo", ANA.id, says("Hi"));
        await flush();
        expect(thread.querySelector(".chat-input").value).toBe("Half");
    });

    it("sends files where the conversation takes them", async () => {
        const room = {
            ...bot,
            capabilities: {
                ...bot.capabilities,
                attachments: { types: ["image", "video", "audio", "file"] },
            },
        };
        const { thread, server } = await setup({
            rooms: [[room, []]],
            thread: "!bot:demo",
        });
        const input = thread.querySelector(".chat-file-input");
        expect(input.accept).toBe("image/*,video/*,audio/*");
        const click = vi.spyOn(input, "click");
        thread.querySelector(".chat-attach").click();
        expect(click).toHaveBeenCalled();

        const pick = (file) => {
            Object.defineProperty(input, "files", {
                configurable: true,
                value: file ? [file] : [],
            });
            input.dispatchEvent(new Event("change"));
        };
        pick(new File(["x"], "a.png", { type: "image/png" }));
        pick(new File(["x"], "a.pdf", { type: "application/pdf" }));
        pick(null);
        await flush();
        const sent = server.received
            .filter((r) => r.path.includes("/send/"))
            .map((r) => r.body);
        expect(sent[0]).toMatchObject({
            msgtype: "m.image",
            body: "a.png",
            url: expect.stringMatching(/^mxc:/),
            info: { mimetype: "image/png", size: 1 },
        });
        expect(sent[1]).toMatchObject({ msgtype: "m.file", filename: "a.pdf" });
    });

    it("says when a file can't be sent", async () => {
        const room = {
            ...bot,
            capabilities: {
                ...bot.capabilities,
                attachments: { types: ["image"] },
            },
        };
        const { thread, client } = await setup({
            rooms: [[room, []]],
            thread: "!bot:demo",
        });
        const errors = [];
        thread.addEventListener("uploaderror", (event) =>
            errors.push(event.detail.error.message),
        );
        const input = thread.querySelector(".chat-file-input");
        const pick = (file) => {
            Object.defineProperty(input, "files", {
                configurable: true,
                value: [file],
            });
            input.dispatchEvent(new Event("change"));
        };
        pick(new File(["x"], "a.pdf", { type: "application/pdf" }));
        vi.spyOn(client, "upload").mockRejectedValueOnce(new Error("Too big"));
        pick(new File(["x"], "b.png", { type: "image/png" }));
        await flush();
        expect(errors).toEqual(["unsupported", "Too big"]);
        // Without attachments: no button.
        expect(thread.querySelector(".chat-file-input").accept).toBe("image/*");
        const { thread: plain } = await setup({
            rooms: [[whatsapp, []]],
            thread: "!wa:demo",
        });
        expect(plain.querySelector(".chat-attach")).toBe(null);
    });

    it("renders what a site registered, and keeps a node it returns", async () => {
        registerMsgtype("com.acme.ping", () => document.createTextNode("pong"));
        const { thread } = await setup({
            rooms: [
                [
                    whatsapp,
                    [
                        {
                            sender: ANA.id,
                            content: { msgtype: "com.acme.ping", body: "ping" },
                        },
                    ],
                ],
            ],
            thread: "!wa:demo",
        });
        expect(
            messages(thread)[0].querySelector(".chat-bubble").textContent,
        ).toBe("pong");
        unregisterMsgtype("com.acme.ping");
    });

    it("takes its texts, and rebinds to another conversation", async () => {
        const { thread, client } = await setup({
            rooms: [
                [whatsapp, [{ sender: ANA.id, content: says("Hi") }]],
                [bot, []],
            ],
            thread: "!wa:demo",
        });
        thread.texts = { send: "Enviar" };
        expect(thread.texts.send).toBe("Enviar");
        expect(thread.texts.retry).toBe(TEXTS.retry);
        expect(thread.querySelector(".chat-send").textContent).toBe("Enviar");
        thread.setAttribute("conversation", "!bot:demo");
        expect(thread.store).toBe(client.room("!bot:demo"));
        expect(messages(thread)).toHaveLength(0);
        thread.remove();
        client.room("!bot:demo").changed(); // Not listened to any more.
        expect(thread.client).toBe(client);
    });

    it("waits for its client, its conversation and the page", async () => {
        const { client } = await setup({ rooms: [[whatsapp, []]] });
        const thread = document.createElement("chat-thread");
        thread.client = client; // Not in the page yet: nothing.
        expect(thread.store).toBe(null);
        thread.texts = {};
        document.body.append(thread);
        expect(thread.store).toBe(null); // No conversation.
        thread.setAttribute("conversation", "!wa:demo");
        expect(thread.store.id).toBe("!wa:demo");
    });
});
