import { afterEach, describe, expect, it } from "vitest";
import {
    DEFAULT_REACTIONS,
    reactionEmojis,
} from "../../src/django_chat_ui/static/django_chat_ui/protocol.js";
import { flush, ME, setup } from "./helpers.js";

const ANA = { id: "p_ana", kind: "contact", name: "Ana" };

function conversation(reactions) {
    return {
        id: "conv_wa",
        channel: "whatsapp",
        participants: [ME, ANA],
        capabilities: { reactions, composer: { mode: "free" } },
    };
}

const MESSAGES = [
    {
        id: "m1",
        conversation: "conv_wa",
        author: "p_ana",
        createdAt: "2026-10-20T10:00:00Z",
        parts: [{ type: "text", text: "Hi" }],
        reactions: [
            { emoji: "👍", by: ["p_ana", "p_me"] },
            { emoji: "😂", by: [] },
        ],
    },
    {
        id: "m2",
        conversation: "conv_wa",
        author: "p_me",
        createdAt: "2026-10-20T10:01:00Z",
        parts: [{ type: "text", text: "Hello" }],
    },
];

async function thread(reactions, messages = MESSAGES) {
    return setup({
        conversations: [[conversation(reactions), messages]],
        thread: "conv_wa",
    });
}

const row = (thread, id) =>
    thread.querySelector(`[data-id="${id}"] .chat-reactions`);
const node = (thread, id) => thread.querySelector(`[data-id="${id}"]`);

afterEach(() => {
    document.body.replaceChildren();
});

describe("reactions", () => {
    it("shows who reacted, and toggles one's own", async () => {
        const { server, thread: element } = await thread(true);
        const [thumbs, ...others] = row(element, "m1").querySelectorAll(
            ".chat-reaction",
        );

        expect(others).toEqual([]); // nobody's left: not shown
        expect(thumbs.textContent).toBe("👍2");
        expect(thumbs.title).toBe("Ana, You");
        expect(thumbs.getAttribute("aria-label")).toBe("👍 Ana, You");
        expect(thumbs.getAttribute("aria-pressed")).toBe("true");

        thumbs.click();
        await flush();
        const react = server.received.filter((f) => f.type === "message.react");
        expect(react.at(-1).data).toEqual({
            id: "m1",
            emoji: "👍",
            active: false,
        });
        const after = node(element, "m1").querySelector(".chat-reaction");
        expect(after.textContent).toBe("👍1");
        expect(after.getAttribute("aria-pressed")).toBe("false");

        after.click();
        await flush();
        expect(server.received.at(-1).data.active).toBe(true);
        expect(
            node(element, "m1").querySelector(".chat-reaction").textContent,
        ).toBe("👍2");
    });

    it("picks a reaction from the conversation's", async () => {
        const { server, thread: element } = await thread({
            emojis: ["✅", "👀"],
        });
        // No reactions yet: no line for them, the button by the time.
        expect(row(element, "m2")).toBeNull();
        const add = node(element, "m2").querySelector(".chat-meta .chat-react");
        expect(add.getAttribute("aria-label")).toBe("React");
        expect(add.getAttribute("aria-expanded")).toBe("false");

        add.click();
        const picker = node(element, "m2").querySelector(".chat-react-picker");
        const choices = [...picker.querySelectorAll(".chat-react-choice")];
        expect(choices.map((c) => c.textContent)).toEqual(["✅", "👀"]);
        expect(document.activeElement).toBe(choices[0]);
        expect(
            node(element, "m2")
                .querySelector(".chat-react")
                .getAttribute("aria-expanded"),
        ).toBe("true");

        choices[1].click();
        await flush();
        expect(server.received.at(-1).data).toEqual({
            id: "m2",
            emoji: "👀",
            active: true,
        });
        expect(
            node(element, "m2").querySelector(".chat-react-picker"),
        ).toBeNull();
        expect(document.activeElement).toBe(
            node(element, "m2").querySelector(".chat-react"),
        );
        expect(
            node(element, "m2").querySelector(".chat-reaction").textContent,
        ).toBe("👀1");

        // Chosen again from the picker: taken back.
        node(element, "m2").querySelector(".chat-react").click();
        const pressed = node(element, "m2").querySelector(
            '.chat-react-choice[aria-pressed="true"]',
        );
        expect(pressed.textContent).toBe("👀");
        pressed.click();
        await flush();
        expect(server.received.at(-1).data.active).toBe(false);
    });

    it("closes the picker with Escape, or its button", async () => {
        const { thread: element } = await thread(true);
        node(element, "m2").querySelector(".chat-react").click();
        const picker = node(element, "m2").querySelector(".chat-react-picker");
        expect([...picker.children].map((c) => c.textContent)).toEqual(
            DEFAULT_REACTIONS,
        );

        picker.dispatchEvent(
            new KeyboardEvent("keydown", { key: "Escape", bubbles: true }),
        );
        expect(
            node(element, "m2").querySelector(".chat-react-picker"),
        ).toBeNull();
        expect(document.activeElement).toBe(
            node(element, "m2").querySelector(".chat-react"),
        );

        node(element, "m2").querySelector(".chat-react").click();
        row(element, "m2")
            .querySelector(".chat-react-picker")
            .dispatchEvent(
                new KeyboardEvent("keydown", { key: "a", bubbles: true }),
            );
        expect(
            node(element, "m2").querySelector(".chat-react-picker"),
        ).not.toBeNull();
        node(element, "m2").querySelector(".chat-react").click();
        expect(
            node(element, "m2").querySelector(".chat-react-picker"),
        ).toBeNull();
    });

    it("only shows them where the conversation doesn't allow reacting", async () => {
        const { thread: element } = await thread(false);
        expect(row(element, "m2")).toBeNull();
        const thumbs = node(element, "m1").querySelector(".chat-reaction");
        expect(thumbs.disabled).toBe(true);
        expect(element.querySelector(".chat-react")).toBeNull();
    });

    it("not on messages being sent, failed, streaming or deleted", async () => {
        const at = "2026-10-20T10:02:00Z";
        const base = {
            conversation: "conv_wa",
            author: "p_ana",
            createdAt: at,
            parts: [{ type: "text", text: "x" }],
        };
        const { thread: element } = await thread(true, [
            { ...base, id: "s", streaming: true },
            { ...base, id: "d", deleted: true },
            { ...base, id: "f", author: "p_me", status: "failed" },
        ]);
        for (const id of ["s", "d", "f"]) {
            expect(row(element, id)).toBeNull();
            expect(node(element, id).querySelector(".chat-react")).toBeNull();
        }
    });

    it("keeps what the server says when reacting fails", async () => {
        const { server, thread: element } = await thread(true);
        server.messages.get("conv_wa").length = 0; // the server no longer has it
        node(element, "m2").querySelector(".chat-react").click();
        node(element, "m2").querySelector(".chat-react-choice").click();
        await flush();
        expect(server.received.at(-1).type).toBe("message.react");
        expect(node(element, "m2").querySelector(".chat-reaction")).toBeNull();
    });

    it("are rejected by the fake server where they're off", async () => {
        const { server, client } = await thread(false);
        await expect(client.react("m2", "👍")).rejects.toMatchObject({
            code: "unsupported",
        });
        await expect(client.react("nope", "👍")).rejects.toMatchObject({
            code: "not_found",
        });
        expect(server.received.at(-1).data).toEqual({
            id: "nope",
            emoji: "👍",
            active: true,
        });
    });

    it("keeps the focus where it was when the server updates the thread", async () => {
        const { server, thread: element } = await thread(true);
        node(element, "m1").querySelector(".chat-reaction").focus();
        server.post("conv_wa", "p_ana", [{ type: "text", text: "Another" }]);
        await flush();
        const focused = document.activeElement;
        expect(focused.classList).toContain("chat-reaction");
        expect(focused.dataset.emoji).toBe("👍");
        expect(focused.closest("[data-id]").dataset.id).toBe("m1");

        // Its message gone: nowhere to go back to, nothing breaks.
        element.querySelector(".chat-input").focus();
        server.post("conv_wa", "p_ana", [{ type: "text", text: "More" }]);
        await flush();
        expect(document.activeElement.classList).toContain("chat-input");
    });

    it("are offered from the conversation's emojis", () => {
        expect(reactionEmojis({ capabilities: {} })).toEqual([]);
        expect(reactionEmojis({ capabilities: { reactions: true } })).toEqual(
            DEFAULT_REACTIONS,
        );
        expect(
            reactionEmojis({ capabilities: { reactions: { emojis: [] } } }),
        ).toEqual(DEFAULT_REACTIONS);
        expect(
            reactionEmojis({ capabilities: { reactions: { emojis: ["✅"] } } }),
        ).toEqual(["✅"]);
    });
});
