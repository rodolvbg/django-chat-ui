/**
 * How parts render (protocol section 5): a registry of renderers, one per
 * part type, that build DOM nodes — never HTML from the payload. A part of
 * an unknown type renders as its `fallback`, so none is silently dropped.
 *
 *   import { registerPart } from "./parts.js";
 *   registerPart("acme.order", (part, context) => {
 *       const card = document.createElement("div");
 *       card.textContent = `Order ${part.ext.acme.orderId}`;
 *       return card;
 *   });
 *
 * A renderer gets `(part, context)`; `context` has `message`, `store`,
 * `client`, `texts` and `act(button)` (sends the button's `action`), and
 * returns a Node.
 */

const renderers = new Map();

export function registerPart(type, render) {
    renderers.set(type, render);
}

export function unregisterPart(type) {
    renderers.delete(type);
}

/** The part types this client renders: its capabilities' `parts` (6.2). */
export function registeredParts() {
    return [...renderers.keys()];
}

function element(tag, className, text) {
    const node = document.createElement(tag);
    if (className) node.className = className;
    if (text !== undefined && text !== null) node.textContent = String(text);
    return node;
}

/** Whether a URL from a part may be followed: https, or this site's own
 * (protocol section 11). */
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
    const href = safeUrl(url);
    if (!href) return document.createTextNode(text ?? url ?? "");
    const anchor = element("a", null, text ?? url);
    anchor.href = href;
    anchor.target = "_blank";
    anchor.rel = "noopener noreferrer";
    return anchor;
}

// Markdown, the safe subset: **bold**, *italic*, `code`, [text](url),
// paragraphs, line breaks and "- " lists. Built as nodes: raw HTML in the
// text stays text.

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
    lines(String(text ?? ""), node);
    return node;
}

function buttons(list, context, { persist = false } = {}) {
    const row = element("div", "chat-buttons");
    const message = context.message;
    // Quick replies are for the moment: once one is used, or another
    // message comes, they're done (unless `persist`).
    const later = context.store?.messages.at(-1)?.id !== message.id;
    const used = Boolean(message.ext?.chat?.used);
    for (const button of list ?? []) {
        const node = element(
            "button",
            `chat-button chat-button--${button.style ?? "secondary"}`,
            button.label,
        );
        node.type = "button";
        node.dataset.button = button.id;
        node.disabled = !persist && (later || used);
        node.addEventListener("click", () => context.act(button));
        row.append(node);
    }
    return row;
}

/** Render one part, falling back to its `fallback` text. */
export function renderPart(part, context) {
    const render = renderers.get(part?.type);
    if (render) {
        try {
            return render(part, context);
        } catch {
            // A broken renderer shows the fallback, not a broken thread.
        }
    }
    const node = element(
        "div",
        "chat-part chat-part--fallback",
        part?.fallback ?? context.texts.unsupported,
    );
    if (!part?.fallback) node.classList.add("chat-part--unsupported");
    return node;
}

// The protocol's parts ----------------------------------------------------

registerPart("text", (part) =>
    part.format === "markdown" ? renderMarkdown(part.text) : plain(part.text),
);

registerPart("image", (part) => {
    const src = safeUrl(part.url);
    if (!src) throw new Error("unsafe url");
    const image = element("img", "chat-image");
    image.src = src;
    image.alt = part.alt ?? "";
    image.loading = "lazy";
    if (part.width) image.width = part.width;
    if (part.height) image.height = part.height;
    return image;
});

registerPart("video", (part) => {
    const src = safeUrl(part.url);
    if (!src) throw new Error("unsafe url");
    const video = element("video", "chat-video");
    video.src = src;
    video.controls = true;
    video.preload = "metadata";
    const poster = safeUrl(part.poster);
    if (poster) video.poster = poster;
    return video;
});

registerPart("audio", (part) => {
    const src = safeUrl(part.url);
    if (!src) throw new Error("unsafe url");
    const audio = element(
        "audio",
        part.voice ? "chat-audio chat-audio--voice" : "chat-audio",
    );
    audio.src = src;
    audio.controls = true;
    audio.preload = "metadata";
    return audio;
});

function size(bytes) {
    if (!bytes) return "";
    const units = ["B", "KB", "MB", "GB"];
    let value = bytes;
    let unit = 0;
    while (value >= 1024 && unit < units.length - 1) {
        value /= 1024;
        unit += 1;
    }
    return `${value.toFixed(unit ? 1 : 0)} ${units[unit]}`;
}

registerPart("file", (part) => {
    const file = element("div", "chat-file");
    file.append(link(part.url, part.name ?? part.url));
    if (part.size) file.append(element("span", "chat-file-size", size(part.size)));
    return file;
});

registerPart("location", (part) => {
    const place = element("div", "chat-location");
    const label = part.name ?? `${part.lat}, ${part.lng}`;
    place.append(
        link(
            `https://www.openstreetmap.org/?mlat=${part.lat}&mlon=${part.lng}#map=17/${part.lat}/${part.lng}`,
            label,
        ),
    );
    if (part.address) place.append(element("div", "chat-location-address", part.address));
    return place;
});

registerPart("contact", (part) => {
    const card = element("div", "chat-contact");
    card.append(element("strong", null, part.name));
    for (const value of [...(part.phones ?? []), ...(part.emails ?? [])]) {
        card.append(element("div", null, value));
    }
    return card;
});

registerPart("buttons", (part, context) =>
    buttons(part.buttons, context, { persist: part.persist }),
);

registerPart("link", (part) => {
    const preview = element("div", "chat-link");
    const image = safeUrl(part.image);
    if (image) {
        const img = element("img", "chat-link-image");
        img.src = image;
        img.alt = "";
        preview.append(img);
    }
    preview.append(link(part.url, part.title ?? part.url));
    if (part.description) {
        preview.append(element("div", "chat-link-description", part.description));
    }
    return preview;
});

registerPart("card", (part, context) => {
    const card = element("div", "chat-card");
    const image = safeUrl(part.image);
    if (image) {
        const img = element("img", "chat-card-image");
        img.src = image;
        img.alt = "";
        card.append(img);
    }
    if (part.title) {
        const title = element("div", "chat-card-title");
        title.append(part.url ? link(part.url, part.title) : part.title);
        card.append(title);
    }
    if (part.text) card.append(plain(part.text));
    if (part.buttons?.length) card.append(buttons(part.buttons, context));
    return card;
});

registerPart("system", (part) => element("div", "chat-system", part.text));

registerPart("template", (part) =>
    plain(part.fallback ?? `[${part.template}]`),
);
