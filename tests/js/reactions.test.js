import { afterEach, describe, expect, it, vi } from "vitest";
import { ANA, flush, ME, messages, says, setup, stopAll } from "./helpers.js";

const team = (reactions) => ({
    id: "!team:demo",
    members: [ME.id, ANA.id],
    capabilities: { reactions },
});

afterEach(() => {
    stopAll();
    document.body.replaceChildren();
    vi.restoreAllMocks();
});

async function thread(
    reactions = true,
    history = [{ sender: ANA.id, content: says("Hi") }],
) {
    return setup({ rooms: [[team(reactions), history]], thread: "!team:demo" });
}

describe("reactions in <chat-thread>", () => {
    it("are offered only where the conversation allows them", async () => {
        const { thread: off } = await thread(false);
        expect(off.querySelector(".chat-react")).toBe(null);
        expect(off.querySelector(".chat-reactions")).toBe(null);
    });

    it("are picked, shown with who, and taken back", async () => {
        const { thread: element, server, client } = await thread(true);
        const [hi] = messages(element);
        const open = hi.querySelector(".chat-react");
        expect(open.getAttribute("aria-expanded")).toBe("false");
        expect(open.title).toBe("React");
        open.click();
        const picker = messages(element)[0].querySelector(".chat-react-picker");
        expect(picker.getAttribute("role")).toBe("group");
        const choices = [...picker.querySelectorAll(".chat-react-choice")];
        expect(choices.map((c) => c.textContent)).toEqual([
            "👍",
            "❤️",
            "😂",
            "😮",
            "😢",
            "🙏",
        ]);
        expect(document.activeElement).toBe(choices[0]);
        expect(
            messages(element)[0]
                .querySelector(".chat-react")
                .getAttribute("aria-expanded"),
        ).toBe("true");
        choices[1].click();
        await flush();

        const id = client.room("!team:demo").messages[0].id;
        server.event("!team:demo", ANA.id, "m.reaction", {
            "m.relates_to": {
                rel_type: "m.annotation",
                event_id: id,
                key: "❤️",
            },
        });
        await flush();
        const [heart] = messages(element)[0].querySelectorAll(".chat-reaction");
        expect(heart.textContent).toBe("❤️2");
        expect(heart.title).toBe("You, Ana García");
        expect(heart.getAttribute("aria-label")).toBe("❤️ You, Ana García");
        expect(heart.getAttribute("aria-pressed")).toBe("true");
        expect(messages(element)[0].querySelector(".chat-react-picker")).toBe(
            null,
        );

        // Pressing it again takes theirs back.
        heart.click();
        await flush();
        const left = messages(element)[0].querySelector(".chat-reaction");
        expect(left.textContent).toBe("❤️1");
        expect(left.getAttribute("aria-pressed")).toBe("false");
        left.click(); // And again: theirs too.
        await flush();
        expect(
            messages(element)[0].querySelector(".chat-reaction").textContent,
        ).toBe("❤️2");
    });

    it("toggle from the picker, and close with Escape or the button", async () => {
        const { thread: element } = await thread({ emojis: ["✅", "👀"] });
        messages(element)[0].querySelector(".chat-react").click();
        let choices =
            messages(element)[0].querySelectorAll(".chat-react-choice");
        expect([...choices].map((c) => c.textContent)).toEqual(["✅", "👀"]);
        choices[0].click();
        await flush();
        messages(element)[0].querySelector(".chat-react").click();
        choices = messages(element)[0].querySelectorAll(".chat-react-choice");
        expect(choices[0].getAttribute("aria-pressed")).toBe("true");
        choices[0].click(); // Taken back.
        await flush();
        expect(messages(element)[0].querySelector(".chat-reaction")).toBe(null);

        messages(element)[0].querySelector(".chat-react").click();
        const picker = messages(element)[0].querySelector(".chat-react-picker");
        picker.dispatchEvent(
            new KeyboardEvent("keydown", { key: "a", bubbles: true }),
        );
        expect(
            messages(element)[0].querySelector(".chat-react-picker"),
        ).not.toBe(null);
        picker.dispatchEvent(
            new KeyboardEvent("keydown", { key: "Escape", bubbles: true }),
        );
        expect(messages(element)[0].querySelector(".chat-react-picker")).toBe(
            null,
        );
        expect(document.activeElement).toBe(
            messages(element)[0].querySelector(".chat-react"),
        );
        messages(element)[0].querySelector(".chat-react").click();
        messages(element)[0].querySelector(".chat-react").click();
        expect(messages(element)[0].querySelector(".chat-react-picker")).toBe(
            null,
        );
    });

    it("show who, also those the room doesn't know", async () => {
        const { thread: element, server, client } = await thread(true);
        const id = client.room("!team:demo").messages[0].id;
        server.event("!team:demo", "@gone:demo", "m.reaction", {
            "m.relates_to": {
                rel_type: "m.annotation",
                event_id: id,
                key: "👍",
            },
        });
        await flush();
        expect(messages(element)[0].querySelector(".chat-reaction").title).toBe(
            "?",
        );
        // Not offered any more: shown, not pressed.
        server.setCapabilities("!team:demo", { reactions: false });
        await flush();
        expect(
            messages(element)[0].querySelector(".chat-reaction").disabled,
        ).toBe(true);
        expect(messages(element)[0].querySelector(".chat-react")).toBe(null);
    });

    it("aren't offered on what's being sent, and fail quietly", async () => {
        const { thread: element, server, client } = await thread(true, []);
        server.reject = () => ({ errcode: "M_FORBIDDEN" });
        element.send(says("Hi"));
        expect(messages(element)[0].querySelector(".chat-react")).toBe(null);
        await flush();
        server.reject = null;
        server.post("!team:demo", ANA.id, says("Hello"));
        await flush();
        // The server's go before what's still the client's own.
        const [hello, mine] = messages(element);
        expect(mine.dataset.status).toBe("failed");
        expect(mine.querySelector(".chat-react")).toBe(null);
        vi.spyOn(client, "react").mockRejectedValue(new Error("x"));
        hello.querySelector(".chat-react").click();
        messages(element)[0].querySelector(".chat-react-choice").click();
        await flush();
        expect(messages(element)[0].querySelector(".chat-reaction")).toBe(null);
    });

    it("keep the focus on what had it, across renders", async () => {
        const { thread: element, server } = await thread(true);
        const react = messages(element)[0].querySelector(".chat-react");
        react.focus();
        server.post("!team:demo", ANA.id, says("More"));
        await flush();
        expect(document.activeElement).toBe(
            messages(element)[0].querySelector(".chat-react"),
        );
        // Something without a class, or a message gone: nothing to refocus.
        const bubble = messages(element)[0].querySelector(".chat-bubble");
        bubble.tabIndex = 0;
        bubble.className = "";
        bubble.focus();
        element.render();
        element.list.tabIndex = -1;
        element.list.focus();
        element.render();
        expect(element.focused()).toBe(null);
        element.refocus({ message: "$gone", className: "chat-react" });
        element.refocus(null);
    });
});
