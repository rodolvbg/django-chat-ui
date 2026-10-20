import { describe, expect, it, vi } from "vitest";
import { ConversationStore } from "../../src/django_chat_ui/static/django_chat_ui/store.js";

const at = (minute) => `2026-10-20T10:${String(minute).padStart(2, "0")}:00Z`;

function message(id, minute, extra = {}) {
    return {
        id,
        conversation: "c1",
        author: "p_a",
        parts: [{ type: "text", text: id }],
        createdAt: at(minute),
        ...extra,
    };
}

describe("ConversationStore", () => {
    it("keeps the conversation, merging partial updates", () => {
        const store = new ConversationStore("c1");
        store.apply({
            type: "conversation.created",
            data: {
                id: "c1",
                title: "Ana",
                capabilities: { receipts: true, composer: { mode: "free" } },
            },
        });
        store.apply({
            type: "conversation.updated",
            data: {
                id: "c1",
                capabilities: { composer: { mode: "templates" } },
            },
        });

        expect(store.conversation.title).toBe("Ana");
        expect(store.conversation.capabilities).toEqual({
            receipts: true,
            composer: { mode: "templates" },
        });
        expect(store.conversation.capabilities.composer).toEqual({
            mode: "templates",
        });
    });

    it("ignores other conversations and unknown events", () => {
        const store = new ConversationStore("c1");
        const change = vi.fn();
        store.addEventListener("change", change);

        expect(
            store.apply({ type: "conversation.updated", data: { id: "c2" } }),
        ).toBe(false);
        expect(
            store.apply({ type: "conversation.created", data: { id: "c2" } }),
        ).toBe(false);
        expect(
            store.apply({
                type: "message.created",
                data: { ...message("m", 1), conversation: "c2" },
            }),
        ).toBe(false);
        for (const type of [
            "message.updated",
            "message.delta",
            "typing",
            "read",
            "history",
        ]) {
            expect(store.apply({ type, data: { conversation: "c2" } })).toBe(
                false,
            );
        }
        expect(store.apply({ type: "acme.order.shipped", data: {} })).toBe(
            false,
        );
        expect(
            store.apply({
                type: "message.updated",
                data: { conversation: "c1", id: "nope" },
            }),
        ).toBe(false);
        expect(
            store.apply({
                type: "message.delta",
                data: { conversation: "c1", id: "nope" },
            }),
        ).toBe(false);
        expect(store.apply({ type: "typing" })).toBe(false);
        expect(change).not.toHaveBeenCalled();
    });

    it("orders messages by time and skips replayed ones", () => {
        const store = new ConversationStore("c1");
        store.apply({ type: "message.created", data: message("b", 2) });
        store.apply({ type: "message.created", data: message("a", 1) });
        store.apply({ type: "message.created", data: message("c", 2) });
        store.apply({ type: "message.created", data: message("a", 1) });

        expect(store.messages.map((m) => m.id)).toEqual(["a", "b", "c"]);
    });

    it("matches the server's copy of an optimistic message", () => {
        const store = new ConversationStore("c1");
        store.addPending(message("c_1", 5, { clientId: "c_1" }));
        expect(store.messages[0].status).toBe("sending");
        store.fail("c_1", { message: "offline" });
        expect(store.messages[0].status).toBe("failed");
        store.fail("unknown", {});

        store.apply({
            type: "message.created",
            data: message("m_9", 6, { clientId: "c_1", status: "sent" }),
        });

        expect(store.messages).toHaveLength(1);
        expect(store.messages[0]).toMatchObject({ id: "m_9", status: "sent" });
        expect(store.messages[0].error).toBeUndefined();
    });

    it("updates messages, and streams text into them", () => {
        const store = new ConversationStore("c1");
        store.apply({
            type: "message.created",
            data: message("m", 1, { parts: [], streaming: true }),
        });
        store.apply({
            type: "message.delta",
            data: { conversation: "c1", id: "m", part: 0, text: "Hel" },
        });
        store.apply({
            type: "message.delta",
            data: { conversation: "c1", id: "m", part: 0, text: "lo" },
        });
        expect(store.find("m").parts).toEqual([
            { type: "text", text: "Hello" },
        ]);

        store.apply({
            type: "message.updated",
            data: {
                conversation: "c1",
                id: "m",
                streaming: false,
                status: "read",
            },
        });
        expect(store.find("m")).toMatchObject({
            streaming: false,
            status: "read",
        });

        store.find("m").parts.push({ type: "image", url: "https://x/i.png" });
        expect(
            store.apply({
                type: "message.delta",
                data: { conversation: "c1", id: "m", part: 1, text: "x" },
            }),
        ).toBe(false);
    });

    it("follows typing and reading", () => {
        const store = new ConversationStore("c1");
        store.apply({
            type: "typing",
            data: { conversation: "c1", participant: "p_a", active: true },
        });
        expect([...store.typing]).toEqual(["p_a"]);
        store.apply({
            type: "typing",
            data: { conversation: "c1", participant: "p_a", active: false },
        });
        expect(store.typing.size).toBe(0);

        store.apply({
            type: "read",
            data: { conversation: "c1", participant: "p_a", until: "m" },
        });
        expect(store.readUntil.get("p_a")).toBe("m");
    });

    it("adds pages of history", () => {
        const store = new ConversationStore("c1");
        store.apply({ type: "message.created", data: message("new", 9) });
        store.apply({
            type: "history",
            data: {
                conversation: "c1",
                messages: [message("old", 1), message("new", 9)],
                before: "old",
                more: true,
            },
        });
        expect(store.messages.map((m) => m.id)).toEqual(["old", "new"]);
        expect([store.more, store.before]).toEqual([true, "old"]);

        store.apply({
            type: "history",
            data: { conversation: "c1", more: false },
        });
        expect([store.more, store.before]).toEqual([false, null]);
    });

    it("maps its participants", () => {
        const store = new ConversationStore("c1");
        expect(store.participants.size).toBe(0);
        store.apply({
            type: "conversation.created",
            data: { id: "c1", participants: [{ id: "p_a", kind: "bot" }] },
        });
        expect(store.participants.get("p_a").kind).toBe("bot");
    });
});
