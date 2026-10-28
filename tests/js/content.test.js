import { afterEach, describe, expect, it, vi } from "vitest";
import {
    registerMsgtype,
    renderContent,
    renderHtml,
    renderMarkdown,
    safeUrl,
    unregisterMsgtype,
} from "../../src/django_chat_ui/static/django_chat_ui/content.js";
import {
    BUTTONS,
    CARD,
    CONTACT,
    HTML,
    LINK,
    TEMPLATE,
} from "../../src/django_chat_ui/static/django_chat_ui/matrix.js";
import { withButtons } from "./helpers.js";

function context(extra = {}) {
    const message = { id: "$1" };
    return {
        message,
        store: { lastMessage: message },
        texts: { unsupported: "Can't show it." },
        media: (uri) =>
            uri?.startsWith("mxc://") ? `/media/${uri.slice(6)}` : uri,
        act: vi.fn(),
        ...extra,
    };
}

function render(content, extra) {
    return renderContent(content, context(extra));
}

afterEach(() => unregisterMsgtype("com.acme.order"));

describe("content.js", () => {
    it("follows only safe URLs", () => {
        expect(safeUrl("https://a.b/c")).toBe("https://a.b/c");
        expect(safeUrl("/local")).toBe(`${window.location.origin}/local`);
        expect(safeUrl("javascript:alert(1)")).toBe(null);
        expect(safeUrl("http://other.example/")).toBe(null);
        expect(safeUrl("http://[")).toBe(null);
        expect(safeUrl("")).toBe(null);
        expect(safeUrl(5)).toBe(null);
    });

    it("rebuilds HTML from the safe subset", () => {
        const node = renderHtml(
            '<p>Hi <b>there</b> <a href="https://a.b">link</a> <a href="javascript:x">bad</a></p>' +
                "<script>alert(1)</script><mx-reply>quoted</mx-reply>" +
                '<font color="red">red</font><img src="x" onerror="alert(1)"><!-- c -->' +
                "<ul><li>one</li></ul><pre><code>x</code></pre>",
        );
        expect(node.className).toBe("chat-markdown");
        expect(node.innerHTML).toBe(
            '<p>Hi <b>there</b> <a href="https://a.b/" target="_blank" rel="noopener noreferrer">link</a> bad</p>' +
                "red<ul><li>one</li></ul><pre><code>x</code></pre>",
        );
    });

    it("renders markdown, as it's being written", () => {
        const node = renderMarkdown(
            "**Hi** *you* `x` [a](https://a.b) [b](javascript:x)\nline\n\n- one\n- two",
        );
        expect(node.innerHTML).toBe(
            '<p><strong>Hi</strong> <em>you</em> <code>x</code> <a href="https://a.b/" target="_blank" rel="noopener noreferrer">a</a> b<br>line</p>' +
                "<ul><li>one</li><li>two</li></ul>",
        );
        const writing = render({
            msgtype: "m.text",
            body: "**a**",
            markdown: true,
        });
        expect(writing.querySelector("strong").textContent).toBe("a");
        expect(render({ msgtype: "m.text", markdown: true }).textContent).toBe(
            "",
        );
    });

    it("renders texts, notices and emotes", () => {
        const plain = render({ msgtype: "m.text", body: "a\n<b>b</b>" });
        expect(plain.className).toBe("chat-text");
        expect(plain.innerHTML).toBe("a<br>&lt;b&gt;b&lt;/b&gt;");
        const html = render({
            msgtype: "m.notice",
            body: "a",
            format: HTML,
            formatted_body: "<em>a</em>",
        });
        expect(html.innerHTML).toBe("<em>a</em>");
        expect(
            render({ msgtype: "m.emote", body: "waves", format: HTML })
                .textContent,
        ).toBe("waves");
        expect(render({ msgtype: "m.text" }).textContent).toBe("");
    });

    it("renders quick replies, for the moment", () => {
        const options = [
            { id: "y", label: "Yes", style: "primary" },
            { id: "n", label: "No" },
        ];
        const ctx = context();
        const node = renderContent(withButtons("Pick:", options), ctx);
        expect(node.className).toBe("chat-quick");
        expect(node.querySelector(".chat-text").textContent).toBe("Pick:");
        const [yes, no] = node.querySelectorAll("button");
        expect(yes.className).toBe("chat-button chat-button--primary");
        expect(no.className).toBe("chat-button chat-button--secondary");
        expect(yes.dataset.button).toBe("y");
        expect(yes.disabled).toBe(false);
        yes.click();
        expect(ctx.act).toHaveBeenCalledWith(options[0]);

        // With its HTML; done once another message came, or one was used.
        const formatted = {
            ...withButtons("Pick:", options),
            [BUTTONS]: {
                body: "Pick",
                formatted_body: "<b>Pick</b>",
                buttons: options,
            },
        };
        const later = renderContent(
            formatted,
            context({ store: { lastMessage: { id: "$2" } } }),
        );
        expect(later.querySelector("b").textContent).toBe("Pick");
        expect(
            [...later.querySelectorAll("button")].every((b) => b.disabled),
        ).toBe(true);
        const used = renderContent(
            withButtons("x", options),
            context({ message: { id: "$1", used: true } }),
        );
        expect(used.querySelector("button").disabled).toBe(true);
        const kept = renderContent(
            withButtons("x", options, { persist: true }),
            context({ message: { id: "$1", used: true }, store: null }),
        );
        expect(kept.querySelector("button").disabled).toBe(false);
        // No buttons: its text.
        expect(
            render({ msgtype: "m.text", body: "t", [BUTTONS]: { buttons: [] } })
                .textContent,
        ).toBe("t");
        expect(
            renderContent(
                {
                    msgtype: "m.text",
                    body: "",
                    [BUTTONS]: { buttons: [{ id: "a" }] },
                },
                context(),
            ).textContent,
        ).toBe("");
    });

    it("renders link buttons: they open their URL, always", () => {
        const options = [
            {
                label: "Track it",
                url: "https://track.example/A-1",
                style: "primary",
            },
            { label: "Invoice", url: "/orders/1/invoice/" },
            { label: "Bad", url: "javascript:alert(1)" },
            { id: "n", label: "No" },
        ];
        const ctx = context({ store: { lastMessage: { id: "$2" } } });
        const node = renderContent(withButtons("Your order:", options), ctx);
        const [track, invoice, ...rest] = node.querySelectorAll("a");
        expect(rest).toHaveLength(0); // Not one to follow: not shown.
        expect(track.className).toBe(
            "chat-button chat-button--primary chat-button--link",
        );
        expect(track.href).toBe("https://track.example/A-1");
        expect(track.target).toBe("_blank");
        expect(track.rel).toBe("noopener noreferrer");
        expect(track.textContent).toBe("Track it");
        expect(invoice.href).toBe(
            `${window.location.origin}/orders/1/invoice/`,
        );
        // Another message came: the quick reply is done, the links aren't.
        expect(node.querySelector("button").disabled).toBe(true);
        track.click();
        expect(ctx.act).not.toHaveBeenCalled();
    });

    it("renders link previews", () => {
        const node = render({
            msgtype: "m.text",
            body: "A\nhttps://a.b",
            [LINK]: {
                url: "https://a.b",
                title: "A",
                description: "About A",
                image: "mxc://demo/i",
            },
        });
        expect(node.className).toBe("chat-link");
        expect(node.querySelector("img").getAttribute("src")).toBe(
            `${window.location.origin}/media/demo/i`,
        );
        expect(node.querySelector("a").textContent).toBe("A");
        expect(node.querySelector(".chat-link-description").textContent).toBe(
            "About A",
        );
        const bare = render({
            msgtype: "m.text",
            body: "x",
            [LINK]: { url: "https://a.b" },
        });
        expect(bare.querySelector("img")).toBe(null);
        expect(bare.textContent).toBe("https://a.b");
    });

    it("renders files, from their mxc:// URIs", () => {
        const image = render({
            msgtype: "m.image",
            body: "A shirt",
            url: "mxc://demo/a",
            info: { w: 2, h: 3 },
        });
        expect(image.tagName).toBe("IMG");
        expect(image.getAttribute("src")).toBe(
            `${window.location.origin}/media/demo/a`,
        );
        expect([image.alt, image.width, image.height, image.loading]).toEqual([
            "A shirt",
            2,
            3,
            "lazy",
        ]);
        expect(render({ msgtype: "m.image", url: "mxc://demo/a" }).alt).toBe(
            "",
        );

        const video = render({
            msgtype: "m.video",
            body: "v",
            url: "https://a.b/v.mp4",
        });
        expect([video.tagName, video.controls]).toEqual(["VIDEO", true]);
        const audio = render({
            msgtype: "m.audio",
            body: "a",
            url: "mxc://demo/a",
        });
        expect(audio.className).toBe("chat-audio");
        const voice = render({
            msgtype: "m.audio",
            body: "a",
            url: "mxc://demo/a",
            "org.matrix.msc3245.voice": {},
        });
        expect(voice.className).toBe("chat-audio chat-audio--voice");

        const file = render({
            msgtype: "m.file",
            body: "Invoice",
            filename: "a.pdf",
            url: "mxc://demo/f",
            info: { size: 1536 },
        });
        expect(file.querySelector("a").textContent).toBe("a.pdf");
        expect(file.querySelector(".chat-file-size").textContent).toBe(
            "1.5 KB",
        );
        const big = render({
            msgtype: "m.file",
            body: "b",
            url: "mxc://demo/f",
            info: { size: 5 * 1024 ** 4 },
        });
        expect(big.querySelector(".chat-file-size").textContent).toBe(
            "5120.0 GB",
        );
        const small = render({
            msgtype: "m.file",
            body: "b",
            url: "mxc://demo/f",
            info: { size: 10 },
        });
        expect(small.querySelector(".chat-file-size").textContent).toBe("10 B");
        expect(render({ msgtype: "m.file" }).textContent).toBe("");
        const nameless = render({ msgtype: "m.file", url: "javascript:x" });
        expect(nameless.textContent).toBe("javascript:x");
        expect(nameless.querySelector("a")).toBe(null);

        // An unsafe URL: its body instead.
        const unsafe = render({
            msgtype: "m.image",
            body: "photo",
            url: "javascript:x",
        });
        expect(unsafe.className).toBe("chat-part chat-part--fallback");
        expect(unsafe.textContent).toBe("photo");
    });

    it("renders places and contacts", () => {
        const place = render({
            msgtype: "m.location",
            body: "Shop",
            geo_uri: "geo:40.4,-3.7",
            [LINK]: { title: "Shop", description: "Main St" },
        });
        const link = place.querySelector("a");
        expect(link.textContent).toBe("Shop");
        expect(link.href).toContain("mlat=40.4&mlon=-3.7");
        expect(place.querySelector(".chat-location-address").textContent).toBe(
            "Main St",
        );
        expect(
            render({
                msgtype: "m.location",
                body: "Here",
                geo_uri: "geo:1,2;u=35",
            }).textContent,
        ).toBe("Here");
        expect(
            render({ msgtype: "m.location", geo_uri: "geo:1,2" }).textContent,
        ).toBe("1, 2");
        expect(
            render({ msgtype: "m.location" }).querySelector("a").href,
        ).toContain("mlat=&mlon=undefined");

        const contact = render({
            msgtype: CONTACT,
            body: "Ana",
            [CONTACT]: { name: "Ana", phones: ["1"], emails: ["a@b.c"] },
        });
        expect(contact.querySelector("strong").textContent).toBe("Ana");
        expect(contact.textContent).toBe("Ana1a@b.c");
        expect(
            render({ msgtype: CONTACT, body: "B", [CONTACT]: { name: "B" } })
                .textContent,
        ).toBe("B");
    });

    it("renders cards and templates", () => {
        const ctx = context();
        const card = renderContent(
            {
                msgtype: CARD,
                body: "Shirt",
                [CARD]: {
                    title: "Shirt",
                    text: "Blue",
                    image: "mxc://demo/s",
                    url: "https://shop/s",
                },
                [BUTTONS]: { buttons: [{ id: "buy", label: "Buy" }] },
            },
            ctx,
        );
        expect(card.querySelector("img").getAttribute("src")).toBe(
            `${window.location.origin}/media/demo/s`,
        );
        expect(card.querySelector(".chat-card-title a").textContent).toBe(
            "Shirt",
        );
        expect(card.querySelector(".chat-text").textContent).toBe("Blue");
        card.querySelector("button").click();
        expect(ctx.act).toHaveBeenCalledWith({ id: "buy", label: "Buy" });
        const titled = render({
            msgtype: CARD,
            body: "x",
            [CARD]: { title: "Only" },
        });
        expect(titled.querySelector(".chat-card-title").textContent).toBe(
            "Only",
        );
        expect(titled.querySelector("a")).toBe(null);
        const linked = render({
            msgtype: CARD,
            body: "x",
            [CARD]: { url: "https://a.b" },
        });
        expect(linked.querySelector("a").textContent).toBe("https://a.b");
        expect(
            render({ msgtype: CARD, body: "x", [CARD]: {} }).children,
        ).toHaveLength(0);

        expect(
            render({
                msgtype: TEMPLATE,
                body: "Hi Ana",
                [TEMPLATE]: { id: "t" },
            }).textContent,
        ).toBe("Hi Ana");
    });

    it("shows what it doesn't know as its body", () => {
        const order = render({ msgtype: "com.acme.order", body: "Order A-1" });
        expect(order.className).toBe("chat-part chat-part--fallback");
        expect(order.textContent).toBe("Order A-1");
        const nothing = render({ msgtype: "com.acme.order" });
        expect(nothing.className).toBe(
            "chat-part chat-part--fallback chat-part--unsupported",
        );
        expect(nothing.textContent).toBe("Can't show it.");
        expect(renderContent(undefined, context()).textContent).toBe(
            "Can't show it.",
        );

        registerMsgtype("com.acme.order", (content) => {
            const node = document.createElement("div");
            node.textContent = `#${content["com.acme.order"].id}`;
            return node;
        });
        expect(
            render({
                msgtype: "com.acme.order",
                body: "x",
                "com.acme.order": { id: 7 },
            }).textContent,
        ).toBe("#7");
        // Broken: its body.
        expect(
            render({ msgtype: "com.acme.order", body: "Order" }).textContent,
        ).toBe("Order");
    });
});
