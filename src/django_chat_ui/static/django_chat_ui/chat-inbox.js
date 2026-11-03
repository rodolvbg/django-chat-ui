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
 *
 * The conversation open is in the page's URL (?conversation=<key>): a
 * reload, the back button or a link lead to it. Attributes: url-param (its
 * name, "conversation"), url-state="off" (not in the URL), url-key (what
 * names it: "local", its room ID without the "!" and one's own server;
 * "id", the room ID; "handle", the contact's, a phone say; "ext.<field>",
 * one of the conversation's ext). Or, in JS, inbox.urlKey = (conversation,
 * me) => key; and inbox.resolveUrlKey = async (key) => room ID, for a key
 * none of the conversations has. A key no conversation has: the room ID.
 */

import "./chat-thread.js";
import { element, format } from "./dom.js";
import { preview } from "./preview.js";
import { followPageTheme, unfollowPageTheme } from "./theme.js";

// What a message is about, in a line: shared with <chat-thread>'s quotes.
export { preview };

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

/** Whoever is outside of a conversation: its contact (not a bot), else
 * someone with a handle. */
function contact(conversation, me) {
    const others = conversation.participants.filter(
        (p) => p.id !== me && p.handle && p.kind !== "bot",
    );
    return others.find((p) => p.kind === "contact") ?? others[0];
}

/** What names a conversation in the URL, by url-key. */
export const URL_KEYS = {
    id: (conversation) => conversation.id,
    // "!1:example.com" → "1", on one's own server (another's: as it is).
    local: (conversation, me) => {
        const match = /^!([^:]+):(.+)$/.exec(conversation.id);
        const server = me?.slice(me.indexOf(":") + 1);
        return match && match[2] === server ? match[1] : conversation.id;
    },
    handle: (conversation, me) => contact(conversation, me)?.handle,
};

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
        /** (conversation, me) => its key in the URL; null: url-key's. */
        this.urlKey = null;
        /** async (key) => the room ID of a key no conversation has. */
        this.resolveUrlKey = null;
        this._pending = null; // The URL's key, until it's found.
        this.onChange = () => {
            this.resolveUrl();
            this.render();
        };
        this.onPopState = () => this.fromUrl(true);
    }

    /** The URL's parameter with the conversation open; null: none. */
    get urlParam() {
        const state = this.getAttribute("url-state");
        if (state === "off" || state === "false") return null;
        return this.getAttribute("url-param") || "conversation";
    }

    /** A conversation's key in the URL: urlKey's, or url-key's. */
    keyOf(conversation) {
        const me = this._client?.me;
        const name = this.getAttribute("url-key") || "local";
        let key;
        if (this.urlKey) key = this.urlKey(conversation, me);
        else if (name.startsWith("ext.")) {
            key = name
                .slice(4)
                .split(".")
                .reduce((value, field) => value?.[field], conversation.ext);
        } else key = (URL_KEYS[name] ?? URL_KEYS.id)(conversation, me);
        return key === undefined || key === null || key === ""
            ? conversation.id
            : String(key);
    }

    /** The conversation a key names: the latest one with it, or the room
     * of that ID; null: none (yet). */
    find(key) {
        const client = this._client;
        if (!client) return null;
        const store = client
            .list()
            .find((store) => this.keyOf(store.conversation) === key);
        if (store) return store.id;
        return client.rooms.get(key)?.joined ? key : null;
    }

    /** The conversation the URL names (on load, back and forward). */
    fromUrl(announce) {
        const param = this.urlParam;
        if (!param) return;
        const key = new URLSearchParams(window.location.search).get(param);
        if (!key) {
            // On load: the one set before (none named); back: none.
            this._pending = null;
            if (announce) this.show(null, true);
            return;
        }
        this._pending = { key, announce };
        this.resolveUrl();
    }

    /** Open the URL's conversation, once it's found (its conversations may
     * be still on their way); none has it: resolveUrlKey's, if any. */
    resolveUrl() {
        const pending = this._pending;
        if (!pending) return;
        const id = this.find(pending.key);
        if (id) {
            this._pending = null;
            this.toUrl(id, true); // Its key now (an old link: a room ID).
            this.show(id, pending.announce);
        } else if (this.resolveUrlKey && !pending.asked && this._client) {
            pending.asked = true;
            this.ask(pending);
        }
    }

    async ask(pending) {
        await this._client.ready; // All its conversations, first.
        if (this._pending !== pending || this.find(pending.key)) {
            return this.resolveUrl();
        }
        const id = await this.resolveUrlKey(pending.key);
        if (this._pending !== pending || !id) return;
        this._pending = null;
        this.show(id, pending.announce);
    }

    show(id, announce) {
        if (id === this._selected) return;
        this.selected = id;
        if (announce) {
            this.dispatchEvent(
                new CustomEvent("select", { detail: { conversation: id } }),
            );
        }
    }

    /** Write the conversation open in the URL, by its key: a new history
     * entry (replace: the same one). */
    toUrl(id, replace = false) {
        const param = this.urlParam;
        if (!param) return;
        const url = new URL(window.location.href);
        const store = id && this._client?.rooms.get(id);
        if (id) url.searchParams.set(param, store ? this.keyOf(store.conversation) : id);
        else url.searchParams.delete(param);
        if (url.href !== window.location.href) {
            const write = replace ? "replaceState" : "pushState";
            window.history[write](window.history.state, "", url);
        }
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
        this.onChange();
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
        followPageTheme(this);
        this.fromUrl(false);
        window.addEventListener("popstate", this.onPopState);
        if (!this.shell) this.build();
        else this.selected = this._selected;
        this.render();
    }

    disconnectedCallback() {
        unfollowPageTheme(this);
        window.removeEventListener("popstate", this.onPopState);
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
        this._pending = null;
        this.selected = id;
        this.toUrl(id);
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
        // How the channel knows whoever is outside (not a bot's handle).
        const outside = contact(conversation, this._client?.me);
        return [conversation.channel, outside?.handle]
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
