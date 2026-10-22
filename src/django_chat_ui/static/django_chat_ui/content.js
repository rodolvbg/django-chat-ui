/**
 * How messages render: a registry of renderers, one per `msgtype`, that
 * build DOM nodes. A message of a type it doesn't know renders as its
 * `body`, as the Matrix specification asks, so none is silently dropped.
 *
 *   import { registerMsgtype } from "./content.js";
 *   registerMsgtype("com.acme.order", (content, context) => {
 *       const card = document.createElement("div");
 *       card.textContent = `Order ${content["com.acme.order"].id}`;
 *       return card;
 *   });
 *
 * A renderer gets `(content, context)`; `context` has `message`, `store`,
 * `client`, `texts`, `media(uri)` (an `mxc://` URI's URL) and `act(button)`
 * (uses a button), and returns a Node. HTML (`formatted_body`) is rebuilt
 * from the specification's safe subset: never inserted as it comes.
 */

import { BUTTONS, CARD, CONTACT, HTML, LINK, TEMPLATE } from "./matrix.js";

const renderers = new Map();

export function registerMsgtype(msgtype, render) {
    renderers.set(msgtype, render);
}

export function unregisterMsgtype(msgtype) {
    renderers.delete(msgtype);
}

function element(tag, className, text) {
    const node = document.createElement(tag);
    if (className) node.className = className;
    if (text !== undefined && text !== null) node.textContent = String(text);
    return node;
}

/** Whether a URL from a message may be followed: https, or this site's
 * own. */
export function safeUrl(url) {
    if (typeof url !== "string" || !url) return null;
    try {
        const parsed = new URL(url, window.location.href);
        if (
            parsed.protocol === "https:" ||
            parsed.origin === window.location.origin
        ) {
            return parsed.href;
        }
    } catch {
        // Not a URL.
    }
    return null;
}

function link(url, text) {
    const label = text ?? url ?? "";
    const href = safeUrl(url);
    if (!href) return document.createTextNode(label);
    const anchor = element("a", null, label);
    anchor.href = href;
    anchor.target = "_blank";
    anchor.rel = "noopener noreferrer";
    return anchor;
}

// HTML: the subset the specification allows, rebuilt node by node from a
// parsed (inert) document. Anything else is its text; scripts, styles and
// reply fallbacks are dropped.

const TAGS = new Set([
    "p",
    "br",
    "strong",
    "b",
    "em",
    "i",
    "u",
    "s",
    "del",
    "code",
    "pre",
    "blockquote",
    "ul",
    "ol",
    "li",
    "a",
    "h1",
    "h2",
    "h3",
    "h4",
    "h5",
    "h6",
    "span",
    "div",
    "sup",
    "sub",
    "hr",
]);
const DROPPED = new Set([
    "script",
    "style",
    "mx-reply",
    "iframe",
    "object",
    "embed",
    "template",
    "head",
    "title",
]);

function rebuild(source, parent) {
    for (const node of source.childNodes) {
        if (node.nodeType === Node.TEXT_NODE) {
            parent.append(document.createTextNode(node.textContent));
            continue;
        }
        if (node.nodeType !== Node.ELEMENT_NODE) continue;
        const tag = node.tagName.toLowerCase();
        if (DROPPED.has(tag)) continue;
        if (!TAGS.has(tag)) {
            rebuild(node, parent); // Its text, without it.
            continue;
        }
        if (tag === "a" && safeUrl(node.getAttribute("href"))) {
            const anchor = link(node.getAttribute("href"), "");
            rebuild(node, anchor);
            parent.append(anchor);
            continue;
        }
        if (tag === "a") {
            rebuild(node, parent); // Not to be followed: its text.
            continue;
        }
        const copy = element(tag);
        rebuild(node, copy);
        parent.append(copy);
    }
}

export function renderHtml(html) {
    const root = element("div", "chat-markdown");
    const parsed = new DOMParser().parseFromString(String(html), "text/html");
    rebuild(parsed.body, root);
    return root;
}

// Markdown, the safe subset (a message being written arrives as it):
// **bold**, *italic*, `code`, [text](url), paragraphs, line breaks and "- "
// lists. Built as nodes: raw HTML in the text stays text.

const INLINE = /(\*\*[^*]+\*\*|\*[^*]+\*|`[^`]+`|\[[^\]]+\]\([^)\s]+\))/;

function inline(text, parent) {
    // split() with a capturing group: odd pieces are the matches, even ones
    // the plain text around them.
    text.split(INLINE).forEach((piece, index) => {
        if (!piece) return;
        if (index % 2 === 0) {
            parent.append(document.createTextNode(piece));
        } else if (piece.startsWith("**")) {
            parent.append(element("strong", null, piece.slice(2, -2)));
        } else if (piece.startsWith("`")) {
            parent.append(element("code", null, piece.slice(1, -1)));
        } else if (piece.startsWith("*")) {
            parent.append(element("em", null, piece.slice(1, -1)));
        } else {
            const [, label, url] = piece.match(/^\[([^\]]+)\]\(([^)\s]+)\)$/);
            parent.append(link(url, label));
        }
    });
}

function lines(text, parent) {
    text.split("\n").forEach((line, index) => {
        if (index) parent.append(element("br"));
        inline(line, parent);
    });
}

export function renderMarkdown(text) {
    const root = element("div", "chat-markdown");
    for (const block of String(text).split(/\n{2,}/)) {
        const rows = block.split("\n");
        if (rows.every((row) => /^[-*] /.test(row))) {
            const list = element("ul");
            for (const row of rows) {
                const item = element("li");
                inline(row.slice(2), item);
                list.append(item);
            }
            root.append(list);
        } else {
            const paragraph = element("p");
            lines(block, paragraph);
            root.append(paragraph);
        }
    }
    return root;
}

function plain(text) {
    const node = element("div", "chat-text");
    String(text ?? "")
        .split("\n")
        .forEach((line, index) => {
            if (index) node.append(element("br"));
            node.append(document.createTextNode(line));
        });
    return node;
}

/** A text: its HTML (sanitized) or its body; markdown while it's being
 * written. */
function text(content) {
    if (content.markdown) return renderMarkdown(content.body ?? "");
    if (content.format === HTML && typeof content.formatted_body === "string") {
        return renderHtml(content.formatted_body);
    }
    return plain(content.body);
}

function buttons(list, context, { persist = false } = {}) {
    const row = element("div", "chat-buttons");
    const message = context.message;
    // Quick replies are for the moment: once one is used, or another
    // message comes, they're done (unless `persist`).
    const later = context.store?.lastMessage?.id !== message.id;
    for (const button of list) {
        const node = element(
            "button",
            `chat-button chat-button--${button.style ?? "secondary"}`,
            button.label,
        );
        node.type = "button";
        node.dataset.button = button.id;
        node.disabled = !persist && (later || Boolean(message.used));
        node.addEventListener("click", () => context.act(button));
        row.append(node);
    }
    return row;
}

/** Render a message's content, falling back to its `body`. */
export function renderContent(content, context) {
    const render = renderers.get(content?.msgtype);
    if (render) {
        try {
            return render(content, context);
        } catch {
            // A broken renderer shows the body, not a broken thread.
        }
    }
    const node = element(
        "div",
        "chat-part chat-part--fallback",
        content?.body || context.texts.unsupported,
    );
    if (!content?.body) node.classList.add("chat-part--unsupported");
    return node;
}

// The message types ----------------------------------------------------------

function textual(content, context) {
    const quick = content[BUTTONS];
    if (quick?.buttons?.length) {
        // The text before the buttons (the body has their labels too).
        const box = element("div", "chat-quick");
        box.append(
            text({
                body: quick.body ?? "",
                format: quick.formatted_body ? HTML : undefined,
                formatted_body: quick.formatted_body,
            }),
            buttons(quick.buttons, context, { persist: quick.persist }),
        );
        return box;
    }
    const preview = content[LINK];
    if (preview?.url) return linkPreview(preview, context);
    return text(content);
}

registerMsgtype("m.text", textual);
registerMsgtype("m.notice", textual);
registerMsgtype("m.emote", textual);

function source(content, context) {
    const src = safeUrl(context.media(content.url));
    if (!src) throw new Error("unsafe url");
    return src;
}

registerMsgtype("m.image", (content, context) => {
    const image = element("img", "chat-image");
    image.src = source(content, context);
    image.alt = content.body ?? "";
    image.loading = "lazy";
    if (content.info?.w) image.width = content.info.w;
    if (content.info?.h) image.height = content.info.h;
    return image;
});

registerMsgtype("m.video", (content, context) => {
    const video = element("video", "chat-video");
    video.src = source(content, context);
    video.controls = true;
    video.preload = "metadata";
    return video;
});

registerMsgtype("m.audio", (content, context) => {
    const voice = "org.matrix.msc3245.voice" in content;
    const audio = element(
        "audio",
        voice ? "chat-audio chat-audio--voice" : "chat-audio",
    );
    audio.src = source(content, context);
    audio.controls = true;
    audio.preload = "metadata";
    return audio;
});

/** A file's size for people (only called with one). */
function size(bytes) {
    const units = ["B", "KB", "MB", "GB"];
    let value = bytes;
    let unit = 0;
    while (value >= 1024 && unit < units.length - 1) {
        value /= 1024;
        unit += 1;
    }
    return `${value.toFixed(unit ? 1 : 0)} ${units[unit]}`;
}

registerMsgtype("m.file", (content, context) => {
    const file = element("div", "chat-file");
    const name = content.filename ?? content.body;
    file.append(link(context.media(content.url), name ?? content.url));
    if (content.info?.size) {
        file.append(element("span", "chat-file-size", size(content.info.size)));
    }
    return file;
});

registerMsgtype("m.location", (content) => {
    const [lat, lng] = String(content.geo_uri ?? "")
        .replace(/^geo:/, "")
        .split(/[,;]/);
    const place = element("div", "chat-location");
    const about = content[LINK] ?? {};
    place.append(
        link(
            `https://www.openstreetmap.org/?mlat=${lat}&mlon=${lng}#map=17/${lat}/${lng}`,
            about.title ?? content.body ?? `${lat}, ${lng}`,
        ),
    );
    if (about.description) {
        place.append(
            element("div", "chat-location-address", about.description),
        );
    }
    return place;
});

registerMsgtype(CONTACT, (content) => {
    const card = element("div", "chat-contact");
    const contact = content[CONTACT];
    card.append(element("strong", null, contact.name));
    for (const value of [
        ...(contact.phones ?? []),
        ...(contact.emails ?? []),
    ]) {
        card.append(element("div", null, value));
    }
    return card;
});

function linkPreview(preview, context) {
    const box = element("div", "chat-link");
    const image = safeUrl(context.media(preview.image));
    if (image) {
        const img = element("img", "chat-link-image");
        img.src = image;
        img.alt = "";
        box.append(img);
    }
    box.append(link(preview.url, preview.title ?? preview.url));
    if (preview.description) {
        box.append(
            element("div", "chat-link-description", preview.description),
        );
    }
    return box;
}

registerMsgtype(CARD, (content, context) => {
    const data = content[CARD];
    const card = element("div", "chat-card");
    const image = safeUrl(context.media(data.image));
    if (image) {
        const img = element("img", "chat-card-image");
        img.src = image;
        img.alt = "";
        card.append(img);
    }
    if (data.title || data.url) {
        // Its link, under its title (or as it, without one).
        const title = element("div", "chat-card-title");
        title.append(
            data.url ? link(data.url, data.title ?? data.url) : data.title,
        );
        card.append(title);
    }
    if (data.text) card.append(plain(data.text));
    const quick = content[BUTTONS]?.buttons;
    if (quick?.length) card.append(buttons(quick, context));
    return card;
});

registerMsgtype(TEMPLATE, (content) => plain(content.body));
