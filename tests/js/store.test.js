import { describe, expect, it, vi } from "vitest";
import {
    ACTION,
    CAPABILITIES,
    CONVERSATION,
    DELIVERED,
    PARTICIPANT,
    STATUS,
    STREAM,
} from "../../src/django_chat_ui/static/django_chat_ui/matrix.js";
import { RoomStore } from "../../src/django_chat_ui/static/django_chat_ui/store.js";

let ids = 0;

function message(sender, body, extra = {}) {
    ids += 1;
    return {
        type: "m.room.message",
        event_id: `$${ids}`,
        sender,
        origin_server_ts: ids,
        content: { msgtype: "m.text", body },
        ...extra,
    };
}

function state(type, key, content) {
    ids += 1;
    return { type, state_key: key, event_id: `$${ids}`, content };
}

function reaction(sender, target, key, extra = {}) {
    ids += 1;
    return {
        type: "m.reaction",
        event_id: `$${ids}`,
        sender,
        content: {
            "m.relates_to": { rel_type: "m.annotation", event_id: target, key },
        },
        ...extra,
    };
}

describe("RoomStore", () => {
    it("takes a room of /sync: its state, timeline, unread", () => {
        const store = new RoomStore("!r");
        const changed = vi.fn();
        store.addEventListener("change", changed);
        store.applySync({
            state: {
                events: [
                    state("m.room.name", "", { name: "Ana" }),
                    state(CONVERSATION, "", {
                        channel: "whatsapp",
                        state: "open",
                    }),
                    state(CAPABILITIES, "", { typing: true }),
                    state("m.room.member", "@a", {
                        membership: "join",
                        displayname: "Ana",
                        [PARTICIPANT]: { kind: "contact", handle: "+1" },
                    }),
                    state("m.room.member", "@b", { membership: "leave" }),
                    state("m.room.member", "@c", { membership: "join" }),
                    { type: "m.room.message", content: {} }, // Not state.
                ],
            },
            timeline: { events: [message("@a", "Hi")], prev_batch: "t5" },
            unread_notifications: { notification_count: 2 },
        });
        expect(changed).toHaveBeenCalledOnce();
        expect(store.joined).toBe(true);
        expect(store.more).toBe(true);
        expect(store.prevBatch).toBe("t5");
        expect(store.unread).toBe(2);
        expect(store.conversation).toEqual({
            id: "!r",
            title: "Ana",
            channel: "whatsapp",
            state: "open",
            ext: undefined,
            capabilities: { typing: true },
            participants: [
                {
                    id: "@a",
                    name: "Ana",
                    kind: "contact",
                    handle: "+1",
                    avatar: undefined,
                    ext: undefined,
                },
                {
                    id: "@c",
                    name: "",
                    kind: "user",
                    handle: undefined,
                    avatar: undefined,
                    ext: undefined,
                },
            ],
            unread: 2,
        });
        // Later syncs keep where older events start; an empty one changes
        // nothing but says so.
        store.applySync({});
        expect(store.prevBatch).toBe("t5");
        expect(new RoomStore("!x").conversation.capabilities).toEqual({});
    });

    it("starts over after a gap, keeping what it's sending", () => {
        const store = new RoomStore("!r");
        store.applySync({ timeline: { events: [message("@a", "old")] } });
        store.addLocal({
            event_id: "~t1",
            txnId: "t1",
            type: "m.room.message",
            content: { body: "mine" },
        });
        store.applySync({
            timeline: { events: [message("@a", "new")], limited: true },
        });
        expect(store.messages.map((m) => m.content.body)).toEqual([
            "new",
            "mine",
        ]);
        expect(store.more).toBe(false);
        store.applySync({
            timeline: { events: [], limited: true, prev_batch: "t1" },
        });
        expect(store.more).toBe(true);
    });

    it("puts the server's events before its own pending ones, once", () => {
        const store = new RoomStore("!r");
        store.addLocal({
            event_id: "~t1",
            txnId: "t1",
            type: "m.room.message",
            content: { body: "mine" },
        });
        const theirs = message("@a", "theirs");
        store.applySync({ timeline: { events: [theirs, theirs] } });
        expect(store.messages.map((m) => m.content.body)).toEqual([
            "theirs",
            "mine",
        ]);
        expect(store.messages[1].status).toBe("sending");
        // Its echo, by its transaction.
        const echo = message("@me", "mine", {
            unsigned: { transaction_id: "t1" },
        });
        store.applySync({ timeline: { events: [echo] } });
        expect(store.events.filter((e) => e.local)).toEqual([]);
        expect(store.messages.map((m) => m.id)).toEqual([
            theirs.event_id,
            echo.event_id,
        ]);
    });

    it("confirms its own events, or marks them failed", () => {
        const store = new RoomStore("!r");
        store.addLocal({
            event_id: "~t1",
            txnId: "t1",
            type: "m.room.message",
            sender: "@me",
            content: { body: "a" },
        });
        store.confirm("t1", "$100");
        expect(store.messages[0]).toMatchObject({
            id: "~t1",
            status: "sent",
            txnId: "t1",
        });
        // Its echo, by its event ID (another device's sync has no txn).
        store.applySync({
            timeline: { events: [message("@me", "a", { event_id: "$100" })] },
        });
        expect(store.messages.map((m) => m.id)).toEqual(["$100"]);

        store.addLocal({
            event_id: "~t2",
            txnId: "t2",
            type: "m.room.message",
            content: { body: "b" },
        });
        store.applySync({
            timeline: { events: [message("@me", "b", { event_id: "$101" })] },
        });
        store.confirm("t2", "$101"); // Already there: the local one goes.
        expect(store.messages.map((m) => m.id)).toEqual(["$100", "$101"]);

        store.addLocal({
            event_id: "~t3",
            txnId: "t3",
            type: "m.room.message",
            content: { body: "c" },
        });
        store.fail("t3", { message: "No" });
        expect(store.messages.at(-1)).toMatchObject({
            status: "failed",
            error: { message: "No" },
        });
        store.confirm("nope", "$1");
        store.fail("nope", {});
        expect(store.findLocal("nope")).toBe(null);
    });

    it("redacts, from the timeline and from older events", () => {
        const store = new RoomStore("!r");
        const one = message("@a", "one");
        const two = message("@a", "two");
        store.applySync({
            timeline: {
                events: [
                    one,
                    two,
                    {
                        type: "m.room.redaction",
                        event_id: "$r1",
                        content: { redacts: one.event_id },
                    },
                    {
                        type: "m.room.redaction",
                        event_id: "$r2",
                        redacts: two.event_id,
                        content: {},
                    },
                    {
                        type: "m.room.redaction",
                        event_id: "$r3",
                        content: { redacts: "$none" },
                    },
                ],
            },
        });
        expect(store.messages.map((m) => m.redacted)).toEqual([true, true]);
        expect(store.messages[0].content).toEqual({});

        const old = message("@a", "old");
        store.prepend(
            [
                {
                    type: "m.room.redaction",
                    event_id: "$r4",
                    content: { redacts: old.event_id },
                },
                {
                    type: "m.room.redaction",
                    event_id: "$r5",
                    redacts: "$gone",
                    content: {},
                },
                old,
                one, // Known already.
            ],
            "t1",
        );
        expect(store.messages[0]).toMatchObject({
            id: old.event_id,
            redacted: true,
        });
        expect(store.more).toBe(true);
        store.prepend([], undefined);
        expect(store.more).toBe(false);
    });

    it("gathers reactions, edits, answers and replies", () => {
        const store = new RoomStore("!r");
        const hi = message("@a", "Hi");
        const menu = message("@bot", "Pick");
        store.applySync({
            timeline: {
                events: [
                    hi,
                    menu,
                    reaction("@b", hi.event_id, "👍"),
                    reaction("@me", hi.event_id, "👍"),
                    reaction("@b", hi.event_id, "🎉", {
                        unsigned: { redacted_because: {} },
                    }),
                    {
                        type: "m.reaction",
                        event_id: "$x1",
                        content: {
                            "m.relates_to": {
                                rel_type: "m.reference",
                                event_id: hi.event_id,
                                key: "?",
                            },
                        },
                    },
                    { type: "m.reaction", event_id: "$x2", content: {} },
                    message("@a", "* Hello", {
                        content: {
                            msgtype: "m.text",
                            body: "* Hello",
                            "m.new_content": {
                                msgtype: "m.text",
                                body: "Hello",
                            },
                            "m.relates_to": {
                                rel_type: "m.replace",
                                event_id: hi.event_id,
                            },
                        },
                    }),
                    message("@b", "* forged", {
                        content: {
                            "m.new_content": { body: "forged" },
                            "m.relates_to": {
                                rel_type: "m.replace",
                                event_id: menu.event_id,
                            },
                        },
                    }),
                    message("@a", "Yes", {
                        content: {
                            msgtype: "m.text",
                            body: "Yes",
                            [ACTION]: { event_id: menu.event_id, button: "y" },
                            "m.relates_to": {
                                "m.in_reply_to": { event_id: menu.event_id },
                            },
                        },
                    }),
                ],
            },
        });
        const [first, second, answer] = store.messages;
        expect(first.content.body).toBe("Hello");
        expect(first.edited).toBe(true);
        expect(first.reactions.map((r) => [r.key, r.by])).toEqual([
            ["👍", ["@b", "@me"]],
        ]);
        // Only its sender edits a message.
        expect(second.content.body).toBe("Pick");
        expect(second.edited).toBe(false);
        expect(second.used).toBe(true);
        expect(answer.replyTo).toBe(menu.event_id);
        expect(store.lastMessage).toBe(answer);
        expect(store.messages).toBe(store.messages); // Kept until a change.
        expect(new RoomStore("!e").lastMessage).toBe(null);
    });

    it("says how far its messages got", () => {
        const store = new RoomStore("!r");
        const one = message("@me", "1");
        const two = message("@me", "2");
        const three = message("@me", "3", {
            unsigned: {
                [STATUS]: { status: "failed", error: { error: "Blocked" } },
            },
        });
        const four = message("@me", "4");
        store.applySync({
            timeline: { events: [one, two, three, four] },
            ephemeral: {
                events: [
                    {
                        type: "m.receipt",
                        content: {
                            [one.event_id]: { "m.read": { "@a": {} } },
                            [two.event_id]: { [DELIVERED]: { "@a": {} } },
                            [four.event_id]: { "m.read": { "@me": {} } },
                            $unknown: { "m.read": { "@b": {} } },
                        },
                    },
                    {
                        type: STATUS,
                        content: { event_id: four.event_id, status: "sent" },
                    },
                ],
            },
        });
        expect(store.messages.map((m) => m.status)).toEqual([
            "read",
            "delivered",
            "failed",
            "sent",
        ]);
        expect(store.messages[2].error).toEqual({ error: "Blocked" });
        // A status event says it failed.
        store.applySync({
            ephemeral: {
                events: [
                    {
                        type: STATUS,
                        content: { event_id: two.event_id, status: "failed" },
                    },
                ],
            },
        });
        expect(store.messages[1].status).toBe("failed");
        expect(store.receipts.get("@a")).toEqual({
            "m.read": one.event_id,
            [DELIVERED]: two.event_id,
        });
    });

    it("follows who is typing and what is being written", () => {
        const store = new RoomStore("!r");
        store.applySync({
            ephemeral: {
                events: [
                    { type: "m.typing", content: { user_ids: ["@a", "@bot"] } },
                    {
                        type: STREAM,
                        content: {
                            id: "s1",
                            sender: "@bot",
                            body: "Hel",
                            markdown: true,
                        },
                    },
                    {
                        type: STREAM,
                        content: { id: "s2", sender: "@bot", body: "x" },
                    },
                    { type: "com.acme.other", content: {} },
                ],
            },
        });
        expect([...store.typing]).toEqual(["@a", "@bot"]);
        const writing = store.messages.at(-2);
        expect(writing).toMatchObject({
            id: "stream:s1",
            sender: "@bot",
            streaming: true,
            content: { msgtype: "m.text", body: "Hel", markdown: true },
        });
        expect(store.messages.at(-1).content.markdown).toBe(false);
        // Its message came (in the same sync as an older update of it).
        store.applySync({
            timeline: {
                events: [
                    message("@bot", "Hello", {
                        content: {
                            msgtype: "m.text",
                            body: "Hello",
                            [STREAM]: { id: "s1" },
                        },
                    }),
                ],
            },
            ephemeral: {
                events: [
                    {
                        type: STREAM,
                        content: { id: "s1", sender: "@bot", body: "Hell" },
                    },
                    { type: STREAM, content: { id: "s2", done: true } },
                    { type: "m.typing" },
                ],
            },
        });
        expect(store.messages.map((m) => m.content.body)).toEqual(["Hello"]);
        expect(store.typing.size).toBe(0);
        // A message stops its sender typing.
        store.typing.add("@a");
        store.applySync({ timeline: { events: [message("@a", "Hi")] } });
        expect(store.typing.has("@a")).toBe(false);
        expect(store.stateContent("m.room.topic")).toBe(null);
    });
});
