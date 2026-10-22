/**
 * <chat-inbox>: an inbox for whoever answers — every conversation of the
 * client, the latest active first, with unread counts and a search, and the
 * one selected in a <chat-thread>. On a narrow container it shows one or
 * the other, with a way back to the list.
 *
 *   <chat-inbox></chat-inbox>
 *   inbox.client = client;       // a ChatClient; then client.start()
 *
 * Properties: client, texts (merged over INBOX_TEXTS), selected (the
 * conversation id shown). Dispatches "select" (detail: { conversation }).
 */

import "./chat-thread.js";
import { element, format } from "./dom.js";
import { BUTTONS, CARD, CONTACT } from "./matrix.js";

export const INBOX_TEXTS = {
    search: "Search conversations",
    empty: "No conversations yet.",
    noResults: "No conversation matches.",
    back: "Back to conversations",
    unread: "%(count)s unread",
    pick: "Pick a conversation.",
    image: "Photo",
    video: "Video",
    audio: "Audio",
    voice: "Voice message",
    location: "Location",
    you: "You",
};

/** Markdown's text, without its marks: [a](b) → a, **a** → a. */
function plain(markdown) {
    return markdown
        .replace(/\[([^\]]*)\]\([^)]*\)/g, "$1")
        .replace(/[*_`]+/g, "")
        .replace(/^\s*[-#>]+\s+/gm, "")
        .replace(/\s+/g, " ")
        .trim();
}

const KINDS = {
    "m.image": "image",
    "m.video": "video",
    "m.audio": "audio",
    "m.location": "location",
};

/** One line saying what a message is about, for the list. */
export function preview(message, texts) {
    if (!message) return "";
    if (message.redacted) return texts.deleted ?? "";
    const content = message.content ?? {};
    if (content.markdown) return plain(content.body ?? "");
    if (content[BUTTONS]) return content[BUTTONS].body ?? "";
    if (
        content.msgtype === "m.audio" &&
        "org.matrix.msc3245.voice" in content
    ) {
        return texts.voice;
    }
    const kind = KINDS[content.msgtype];
    if (kind) return texts[kind];
    if (content.msgtype === "m.file")
        return content.filename ?? content.body ?? "";
    if (content.msgtype === CARD)
        return content[CARD]?.title ?? content.body ?? "";
    if (content.msgtype === CONTACT) return content[CONTACT]?.name ?? "";
    return String(content.body ?? "")
        .replace(/\s+/g, " ")
        .trim();
}

function initials(name) {
    return name
        .split(/\s+/)
        .slice(0, 2)
        .map((word) => word[0] ?? "")
        .join("")
        .toUpperCase();
}

export class ChatInbox extends HTMLElement {
    constructor() {
        super();
        this._client = null;
        this._texts = INBOX_TEXTS;
        this._selected = null;
        this.query = "";
        this.onChange = () => this.render();
    }

    get client() {
        return this._client;
    }

    set client(client) {
        this.unlisten();
        this._client = client;
        client.addEventListener("conversations", this.onChange);
        client.addEventListener("ready", this.onChange);
        if (this.thread) this.thread.client = client;
        this.render();
    }

    get texts() {
        return this._texts;
    }

    set texts(texts) {
        this._texts = { ...INBOX_TEXTS, ...texts };
        if (this.thread) this.thread.texts = texts;
        this.render();
    }

    get selected() {
        return this._selected;
    }

    set selected(id) {
        this._selected = id;
        if (this.thread) {
            if (id) this.thread.setAttribute("conversation", id);
            else this.thread.removeAttribute("conversation");
        }
        this.render();
    }

    connectedCallback() {
        if (!this.shell) this.build();
        this.render();
    }

    disconnectedCallback() {
        this.unlisten();
    }

    unlisten() {
        this._client?.removeEventListener("conversations", this.onChange);
        this._client?.removeEventListener("ready", this.onChange);
    }

    build() {
        this.shell = element("div", "chat-inbox");
        const list = element("aside", "chat-inbox-list");
        this.search = element("input", "chat-inbox-search");
        this.search.type = "search";
        this.search.addEventListener("input", () => {
            this.query = this.search.value.trim().toLowerCase();
            this.render();
        });
        this.items = element("ul", "chat-conversations");
        this.empty = element("p", "chat-inbox-empty");
        list.append(this.search, this.items, this.empty);

        const pane = element("section", "chat-inbox-pane");
        const header = element("header", "chat-inbox-header");
        this.back = element("button", "chat-inbox-back", "←");
        this.back.type = "button";
        this.back.addEventListener("click", () => this.select(null));
        this.heading = element("div", "chat-inbox-title");
        this.subheading = element("div", "chat-inbox-subtitle");
        const titles = element("div", "chat-inbox-titles");
        titles.append(this.heading, this.subheading);
        header.append(this.back, titles);
        this.placeholder = element("p", "chat-inbox-pick");
        this.thread = document.createElement("chat-thread");
        if (this._client) this.thread.client = this._client;
        if (this._selected)
            this.thread.setAttribute("conversation", this._selected);
        pane.append(header, this.placeholder, this.thread);
        this.shell.append(list, pane);
        this.append(this.shell);
    }

    select(id) {
        this.selected = id;
        this.dispatchEvent(
            new CustomEvent("select", { detail: { conversation: id } }),
        );
        if (id) this.thread.querySelector(".chat-input")?.focus();
        else this.items.querySelector(".chat-conversation")?.focus();
    }

    /** The conversations shown: all, or those the search matches. */
    visible() {
        const stores = this._client?.list() ?? [];
        if (!this.query) return stores;
        return stores.filter((store) => {
            const conversation = store.conversation;
            const haystack = [
                conversation.title,
                ...conversation.participants.flatMap((p) => [p.name, p.handle]),
                preview(store.lastMessage, this._texts),
            ]
                .filter(Boolean)
                .join(" ")
                .toLowerCase();
            return haystack.includes(this.query);
        });
    }

    render() {
        if (!this.shell) return;
        const texts = this._texts;
        this.search.placeholder = texts.search;
        this.search.setAttribute("aria-label", texts.search);
        this.back.setAttribute("aria-label", texts.back);
        this.back.title = texts.back;
        this.placeholder.textContent = texts.pick;

        const stores = this.visible();
        this.items.replaceChildren(
            ...stores.map((store) => this.renderItem(store)),
        );
        const total = this._client?.list().length ?? 0;
        this.empty.textContent = total ? texts.noResults : texts.empty;
        this.empty.hidden = stores.length > 0;

        const current =
            this._selected && this._client?.rooms.get(this._selected);
        this.shell.classList.toggle("chat-inbox--open", Boolean(current));
        this.placeholder.hidden = Boolean(current);
        this.thread.hidden = !current;
        if (current) this.thread.markRead(); // Seen now.
        this.heading.textContent = current ? this.title(current) : "";
        this.subheading.textContent = current ? this.subtitle(current) : "";
    }

    title(store) {
        const conversation = store.conversation;
        const me = this._client?.me;
        const others = conversation.participants.filter((p) => p.id !== me);
        return conversation.title ?? others.map((p) => p.name).join(", ");
    }

    subtitle(store) {
        const conversation = store.conversation;
        const me = this._client?.me;
        // How the channel knows whoever is outside (not a bot's handle).
        const others = conversation.participants.filter(
            (p) => p.id !== me && p.handle && p.kind !== "bot",
        );
        const contact = others.find((p) => p.kind === "contact") ?? others[0];
        return [conversation.channel, contact?.handle]
            .filter(Boolean)
            .join(" · ");
    }

    renderItem(store) {
        const conversation = store.conversation;
        const texts = this._texts;
        const item = element("li");
        const button = element("button", "chat-conversation");
        button.type = "button";
        button.dataset.conversation = conversation.id;
        button.dataset.channel = conversation.channel;
        if (conversation.id === this._selected) {
            button.setAttribute("aria-current", "true");
        }
        button.addEventListener("click", () => this.select(conversation.id));

        const title = this.title(store);
        const avatar = element("span", "chat-avatar", initials(title));
        avatar.setAttribute("aria-hidden", "true");
        const body = element("span", "chat-conversation-body");
        const top = element("span", "chat-conversation-top");
        top.append(element("span", "chat-conversation-title", title));
        const last = store.lastMessage;
        if (last?.createdAt) {
            const time = element("time", "chat-conversation-time");
            time.dateTime = new Date(last.createdAt).toISOString();
            time.textContent = new Date(last.createdAt).toLocaleTimeString(
                document.documentElement.lang || undefined,
                { hour: "2-digit", minute: "2-digit" },
            );
            top.append(time);
        }
        const bottom = element("span", "chat-conversation-bottom");
        const mine = last && last.sender === this._client?.me;
        bottom.append(
            element(
                "span",
                "chat-conversation-preview",
                `${mine ? `${texts.you}: ` : ""}${preview(last, texts)}`,
            ),
        );
        if (conversation.unread) {
            const badge = element("span", "chat-unread", conversation.unread);
            badge.setAttribute(
                "aria-label",
                format(texts.unread, { count: conversation.unread }),
            );
            bottom.append(badge);
        }
        body.append(top, bottom);
        button.append(avatar, body);
        item.append(button);
        return item;
    }
}

if (!customElements.get("chat-inbox")) {
    customElements.define("chat-inbox", ChatInbox);
}
