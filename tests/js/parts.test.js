import { afterEach, describe, expect, it, vi } from "vitest";
import { TEXTS } from "../../src/django_chat_ui/static/django_chat_ui/chat-thread.js";
import {
    registeredParts,
    registerPart,
    renderMarkdown,
    renderPart,
    safeUrl,
    unregisterPart,
} from "../../src/django_chat_ui/static/django_chat_ui/parts.js";

function context(extra = {}) {
    return {
        message: { id: "m" },
        store: { messages: [{ id: "m" }] },
        texts: TEXTS,
        act: vi.fn(),
        ...extra,
    };
}

const render = (part, extra) => renderPart(part, context(extra));

describe("parts", () => {
    afterEach(() => unregisterPart("acme.order"));

    it("renders text, keeping its line breaks, and no HTML", () => {
        const node = render({
            type: "text",
            text: 'Hi <img src=x onerror="alert(1)">\nthere',
        });
        expect(node.querySelector("img")).toBeNull();
        expect(node.textContent).toBe('Hi <img src=x onerror="alert(1)">there');
        expect(node.querySelectorAll("br")).toHaveLength(1);
        expect(render({ type: "text" }).textContent).toBe("");
    });

    it("renders the safe markdown subset", () => {
        const node = render({
            type: "text",
            format: "markdown",
            text: "**Bold** *em* `code` [docs](https://example.com) [bad](javascript:alert(1))\n\n- one\n- two\n\n<b>raw</b>",
        });
        expect(node.querySelector("strong").textContent).toBe("Bold");
        expect(node.querySelector("em").textContent).toBe("em");
        expect(node.querySelector("code").textContent).toBe("code");
        const links = node.querySelectorAll("a");
        expect(links).toHaveLength(1);
        expect(links[0].href).toBe("https://example.com/");
        expect(links[0].rel).toBe("noopener noreferrer");
        expect(node.textContent).toContain("bad");
        expect(
            [...node.querySelectorAll("li")].map((li) => li.textContent),
        ).toEqual(["one", "two"]);
        expect(node.querySelector("b")).toBeNull();
        expect(node.textContent).toContain("<b>raw</b>");
        expect(renderMarkdown("**").textContent).toBe("**");
    });

    it("only follows https or same-site URLs", () => {
        expect(safeUrl("https://example.com/a")).toBe("https://example.com/a");
        expect(safeUrl("/media/a.png")).toBe(
            `${window.location.origin}/media/a.png`,
        );
        expect(safeUrl("javascript:alert(1)")).toBeNull();
        expect(safeUrl("http://other.example/")).toBeNull();
        expect(safeUrl("")).toBeNull();
        expect(safeUrl(42)).toBeNull();
        expect(safeUrl("http://[bad")).toBeNull();
    });

    it("renders media, and falls back on an unsafe URL", () => {
        const image = render({
            type: "image",
            url: "https://x/a.png",
            alt: "A",
            width: 10,
            height: 20,
        });
        expect([image.tagName, image.alt, image.width, image.height]).toEqual([
            "IMG",
            "A",
            10,
            20,
        ]);
        expect(render({ type: "image", url: "https://x/a.png" }).alt).toBe("");
        expect(
            render({
                type: "video",
                url: "https://x/v.mp4",
                poster: "https://x/p.png",
            }).poster,
        ).toBe("https://x/p.png");
        expect(
            render({ type: "video", url: "https://x/v.mp4" }).getAttribute(
                "poster",
            ),
        ).toBeNull();
        expect(
            render({ type: "audio", url: "https://x/a.ogg", voice: true })
                .className,
        ).toContain("voice");
        expect(
            render({ type: "audio", url: "https://x/a.ogg" }).className,
        ).toBe("chat-audio");
        for (const type of ["image", "video", "audio"]) {
            const node = render({
                type,
                url: "javascript:x",
                fallback: `a ${type}`,
            });
            expect(node.textContent).toBe(`a ${type}`);
        }
    });

    it("renders files, places, contacts, links and cards", () => {
        const file = render({
            type: "file",
            url: "https://x/f.pdf",
            name: "f.pdf",
            size: 2048,
        });
        expect(file.textContent).toBe("f.pdf2.0 KB");
        expect(
            render({ type: "file", url: "https://x/f.pdf", size: 3 })
                .textContent,
        ).toContain("3 B");
        expect(
            render({ type: "file", url: "javascript:x" }).querySelector("a"),
        ).toBeNull();
        expect(
            render({ type: "file", url: "https://x/f" }).querySelector(
                ".chat-file-size",
            ),
        ).toBeNull();

        const place = render({
            type: "location",
            lat: 1,
            lng: 2,
            address: "Main St",
        });
        expect(place.querySelector("a").href).toContain("openstreetmap.org");
        expect(place.textContent).toContain("1, 2");
        expect(
            render({ type: "location", lat: 1, lng: 2, name: "HQ" })
                .textContent,
        ).toBe("HQ");

        const contact = render({
            type: "contact",
            name: "Ana",
            phones: ["+34 600"],
            emails: ["a@x.es"],
        });
        expect(contact.textContent).toBe("Ana+34 600a@x.es");
        expect(render({ type: "contact", name: "Solo" }).textContent).toBe(
            "Solo",
        );

        const preview = render({
            type: "link",
            url: "https://x",
            title: "X",
            description: "Site",
            image: "https://x/i.png",
        });
        expect(preview.querySelector("img")).not.toBeNull();
        expect(preview.textContent).toBe("XSite");
        expect(render({ type: "link", url: "https://x" }).textContent).toBe(
            "https://x",
        );

        const card = render({
            type: "card",
            title: "Plan",
            text: "Pro",
            image: "https://x/i.png",
            url: "https://x/plan",
            buttons: [{ id: "buy", label: "Buy" }],
        });
        expect(card.querySelector(".chat-card-title a").textContent).toBe(
            "Plan",
        );
        expect(card.querySelector("button").textContent).toBe("Buy");
        expect(
            render({ type: "card", title: "Plain" }).querySelector("a"),
        ).toBeNull();
        expect(render({ type: "card" }).children).toHaveLength(0);
    });

    it("renders buttons that act, for the moment", () => {
        const act = vi.fn();
        const part = {
            type: "buttons",
            buttons: [
                { id: "yes", label: "Yes", style: "primary" },
                { id: "no", label: "No" },
            ],
        };
        const row = render(part, { act });
        const [yes, no] = row.querySelectorAll("button");
        expect(yes.className).toContain("primary");
        expect(no.className).toContain("secondary");
        expect(yes.disabled).toBe(false);
        yes.click();
        expect(act).toHaveBeenCalledWith(part.buttons[0]);

        // A later message, or one already used: done.
        const later = render(part, {
            store: { messages: [{ id: "m" }, { id: "m2" }] },
        });
        expect(later.querySelector("button").disabled).toBe(true);
        const used = render(part, {
            message: { id: "m", ext: { chat: { used: "yes" } } },
        });
        expect(used.querySelector("button").disabled).toBe(true);
        // Unless they persist.
        const persist = render(
            { ...part, persist: true },
            { store: { messages: [{ id: "m" }, { id: "m2" }] } },
        );
        expect(persist.querySelector("button").disabled).toBe(false);
        expect(render({ type: "buttons" }).children).toHaveLength(0);
    });

    it("renders system lines and templates", () => {
        expect(render({ type: "system", text: "Ana joined" }).textContent).toBe(
            "Ana joined",
        );
        expect(
            render({ type: "template", template: "t1", fallback: "Hola Ana" })
                .textContent,
        ).toBe("Hola Ana");
        expect(render({ type: "template", template: "t1" }).textContent).toBe(
            "[t1]",
        );
    });

    it("shows a part it can't render as its fallback, never dropping it", () => {
        const fallback = render({
            type: "acme.order",
            fallback: "Order A-1029",
        });
        expect(fallback.textContent).toBe("Order A-1029");
        expect(fallback.className).toContain("chat-part--fallback");

        const unsupported = render({ type: "acme.thing" });
        expect(unsupported.textContent).toBe(TEXTS.unsupported);
        expect(unsupported.className).toContain("chat-part--unsupported");
        expect(render(undefined).textContent).toBe(TEXTS.unsupported);
    });

    it("lets an extension register its part, and survives a broken one", () => {
        registerPart("acme.order", (part) => {
            const node = document.createElement("div");
            node.className = "order";
            node.textContent = `Order ${part.ext.acme.orderId}`;
            return node;
        });
        expect(registeredParts()).toContain("acme.order");
        expect(
            render({
                type: "acme.order",
                fallback: "x",
                ext: { acme: { orderId: "A1" } },
            }).textContent,
        ).toBe("Order A1");
        // Missing data: the renderer throws, the fallback shows.
        expect(
            render({ type: "acme.order", fallback: "Order (no data)" })
                .textContent,
        ).toBe("Order (no data)");

        unregisterPart("acme.order");
        expect(registeredParts()).not.toContain("acme.order");
    });
});
