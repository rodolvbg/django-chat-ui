import { afterEach, describe, expect, it, vi } from "vitest";
import {
    ANA,
    flush,
    ME,
    messages,
    says,
    setup,
    stopAll,
} from "./helpers.js";

const room = (capabilities = { replies: true }) => ({
    id: "!r:demo",
    members: [ME.id, ANA.id],
    capabilities: { composer: { mode: "free" }, ...capabilities },
});

afterEach(() => {
    stopAll();
    document.body.replaceChildren();
    vi.useRealTimers();
    vi.restoreAllMocks();
});

async function thread(capabilities, history) {
    return setup({
        rooms: [
            [
                room(capabilities),
                history ?? [
                    { sender: ANA.id, content: says("Do you have it in M?") },
                    {
                        sender: ME.id,
                        content: { msgtype: "m.image", body: "shirt.png", url: "x" },
                    },
                ],
            ],
        ],
        thread: "!r:demo",
    });
}

function type(element, value) {
    const input = element.querySelector(".chat-input");
    input.value = value;
    input.dispatchEvent(new Event("input"));
    return input;
}

function key(input, name) {
    const event = new KeyboardEvent("keydown", {
        key: name,
        bubbles: true,
        cancelable: true,
    });
    input.dispatchEvent(event);
    return event;
}

const sentBodies = (server) =>
    server.received
        .filter((r) => r.method === "PUT" && r.path.includes("/send/"))
        .map((r) => r.body);

describe("replies in <chat-thread>", () => {
    it("answers a message, and shows what it answers", async () => {
        const { thread: element, server, client } = await thread();
        const [question] = messages(element);
        const reply = question.querySelector(".chat-reply-button");
        expect(reply.getAttribute("aria-label")).toBe("Reply");
        reply.click();

        const bar = element.querySelector(".chat-reply-bar");
        expect(bar.hidden).toBe(false);
        expect(bar.querySelector(".chat-reply-label").textContent).toBe(
            "Replying to Ana García",
        );
        expect(bar.querySelector(".chat-reply-text").textContent).toBe(
            "Do you have it in M?",
        );
        expect(document.activeElement).toBe(element.querySelector(".chat-input"));

        key(type(element, "Yes!"), "Enter");
        expect(bar.hidden).toBe(true); // Done with it.
        await flush();
        const [sent] = sentBodies(server);
        expect(sent["m.relates_to"]).toEqual({
            "m.in_reply_to": {
                event_id: client.room("!r:demo").messages[0].id,
            },
        });

        // The answer quotes it; choosing the quote brings it into view.
        const answer = messages(element).at(-1);
        const quote = answer.querySelector(".chat-quote");
        expect(quote.querySelector(".chat-quote-author").textContent).toBe(
            "Ana García",
        );
        expect(quote.getAttribute("aria-label")).toBe(
            "Ana García: Do you have it in M?",
        );
        vi.useFakeTimers();
        const scroll = vi.fn();
        messages(element)[0].scrollIntoView = scroll;
        quote.click();
        expect(scroll).toHaveBeenCalledWith({ block: "center", behavior: "smooth" });
        expect(messages(element)[0].classList).toContain(
            "chat-message--highlight",
        );
        vi.advanceTimersByTime(1500);
        expect(messages(element)[0].classList).not.toContain(
            "chat-message--highlight",
        );
    });

    it("quotes one's own messages as theirs, and what isn't text by its kind", async () => {
        const { thread: element } = await thread();
        messages(element)[1].querySelector(".chat-reply-button").click();
        const bar = element.querySelector(".chat-reply-bar");
        expect(bar.querySelector(".chat-reply-label").textContent).toBe(
            "Replying to You",
        );
        expect(bar.querySelector(".chat-reply-text").textContent).toBe("Photo");
    });

    it("is cancelled with its button or Escape", async () => {
        const { thread: element, server } = await thread();
        messages(element)[0].querySelector(".chat-reply-button").click();
        element.querySelector(".chat-reply-cancel").click();
        expect(element.querySelector(".chat-reply-bar").hidden).toBe(true);

        messages(element)[0].querySelector(".chat-reply-button").click();
        const input = type(element, "Never mind");
        expect(key(input, "Escape").defaultPrevented).toBe(true);
        expect(element.querySelector(".chat-reply-bar").hidden).toBe(true);
        expect(key(input, "Escape").defaultPrevented).toBe(false);
        key(input, "Enter");
        await flush();
        expect(sentBodies(server)[0]["m.relates_to"]).toBeUndefined();
    });

    it("answers with a file too", async () => {
        const { thread: element, server } = await thread({
            replies: true,
            attachments: { types: ["file"] },
        });
        messages(element)[0].querySelector(".chat-reply-button").click();
        const input = element.querySelector(".chat-file-input");
        Object.defineProperty(input, "files", {
            value: [new File(["x"], "a.pdf", { type: "application/pdf" })],
        });
        input.dispatchEvent(new Event("change"));
        await flush();
        expect(sentBodies(server)[0]["m.relates_to"]).toBeDefined();
    });

    it("isn't offered where the conversation doesn't take replies", async () => {
        const { thread: element, server, client } = await thread({});
        expect(element.querySelector(".chat-reply-button")).toBe(null);
        // A reply set before it stopped taking them isn't sent.
        element.replying = client.room("!r:demo").messages[0].id;
        element.render();
        expect(element.querySelector(".chat-reply-bar").hidden).toBe(true);
        key(type(element, "Hi"), "Enter");
        await flush();
        expect(sentBodies(server)[0]["m.relates_to"]).toBeUndefined();
    });

    it("leaves templates without a reply", async () => {
        const { thread: element, server, client } = await thread({
            replies: true,
            composer: {
                mode: "templates",
                templates: [{ id: "t", preview: "Hi" }],
            },
        });
        element.replying = client.room("!r:demo").messages[0].id;
        element.render();
        expect(element.querySelector(".chat-reply-bar").hidden).toBe(true);
        element.submit();
        await flush();
        expect(sentBodies(server)[0]["m.relates_to"]).toBeUndefined();
    });

    it("quotes a message that isn't there, and says so", async () => {
        const { thread: element, server } = await thread({ replies: true }, []);
        server.post("!r:demo", ANA.id, {
            ...says("About that…"),
            "m.relates_to": { "m.in_reply_to": { event_id: "$gone" } },
        });
        await flush();
        const quote = messages(element)[0].querySelector(".chat-quote");
        expect(quote.disabled).toBe(true);
        expect(quote.textContent).toBe("A message not loaded");
        element.reveal("$gone"); // Nothing to bring into view.
    });

    it("quotes a deleted message as deleted, and a stranger without a name", async () => {
        const { thread: element, server, client } = await thread();
        const [question] = client.room("!r:demo").messages;
        server.post("!r:demo", "@gone:demo", {
            ...says("Me too"),
            "m.relates_to": { "m.in_reply_to": { event_id: question.id } },
        });
        await flush();
        server.redact("!r:demo", question.id, ANA.id);
        await flush();
        const quote = messages(element).at(-1).querySelector(".chat-quote");
        expect(quote.querySelector(".chat-quote-text").textContent).toBe(
            "Message deleted",
        );
        // Deleted: not to be answered.
        expect(messages(element)[0].querySelector(".chat-reply-button")).toBe(null);
        // Answering the stranger: no name.
        messages(element).at(-1).querySelector(".chat-reply-button").click();
        expect(
            element.querySelector(".chat-reply-label").textContent,
        ).toBe("Replying to ");
    });
});
