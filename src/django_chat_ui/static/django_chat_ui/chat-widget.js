/**
 * <chat-widget>: the floating "contact us" chat of a site — a button that
 * opens a panel with a <chat-thread>. It starts a conversation the first
 * time it's opened (`POST /createRoom`), unless given one, and can remember
 * it across visits.
 *
 *   <chat-widget heading="Soporte" subheading="Te respondemos en minutos"
 *                channel="web" storage-key="support"></chat-widget>
 *   widget.client = client;
 *
 * Attributes:
 *   conversation   an existing conversation to show
 *   with           user IDs to start one with (space-separated; none: the
 *                  site's support team)
 *   channel        the channel of one it starts
 *   storage-key    remember the conversation it started, in localStorage
 *   heading, subheading   the panel's texts
 *   open           present while the panel is open
 *
 * Properties: client, texts (merged over WIDGET_TEXTS).
 */

import "./chat-thread.js";
import { element, format } from "./dom.js";
import { followPageTheme, unfollowPageTheme } from "./theme.js";

export const WIDGET_TEXTS = {
    open: "Chat with us",
    close: "Close the chat",
    heading: "Chat",
    unread: "%(count)s unread",
};

const STORAGE = "django-chat-ui:widget:";

function remembered(key) {
    try {
        return key ? window.localStorage.getItem(STORAGE + key) : null;
    } catch {
        return null; // Storage blocked: a new conversation each visit.
    }
}

function remember(key, id) {
    try {
        if (key) window.localStorage.setItem(STORAGE + key, id);
    } catch {
        // Not remembered, still works.
    }
}

export class ChatWidget extends HTMLElement {
    constructor() {
        super();
        this._client = null;
        this._texts = WIDGET_TEXTS;
        this.onChange = () => this.renderBadge();
        this.onKey = (event) => {
            if (event.key === "Escape" && this.isOpen) {
                this.close();
            }
        };
    }

    static get observedAttributes() {
        return ["heading", "subheading"];
    }

    get client() {
        return this._client;
    }

    set client(client) {
        this._client?.removeEventListener("conversations", this.onChange);
        this._client = client;
        client.addEventListener("conversations", this.onChange);
        if (this.thread) this.thread.client = client;
        this.renderBadge();
    }

    get texts() {
        return this._texts;
    }

    set texts(texts) {
        this._texts = { ...WIDGET_TEXTS, ...texts };
        if (this.thread) this.thread.texts = texts;
        this.renderTexts();
    }

    get isOpen() {
        return this.hasAttribute("open");
    }

    /** The conversation shown: given, remembered, or started on opening. */
    get conversation() {
        return (
            this.getAttribute("conversation") ??
            this.started ??
            remembered(this.getAttribute("storage-key"))
        );
    }

    connectedCallback() {
        followPageTheme(this);
        if (!this.launcher) this.build();
        document.addEventListener("keydown", this.onKey);
        this.renderTexts();
        this.renderBadge();
    }

    disconnectedCallback() {
        unfollowPageTheme(this);
        document.removeEventListener("keydown", this.onKey);
        this._client?.removeEventListener("conversations", this.onChange);
    }

    attributeChangedCallback() {
        this.renderTexts();
    }

    build() {
        this.launcher = element("button", "chat-widget-launcher");
        this.launcher.type = "button";
        this.launcher.setAttribute("aria-expanded", "false");
        this.icon = element("span", "chat-widget-icon", "💬");
        this.icon.setAttribute("aria-hidden", "true");
        this.badge = element("span", "chat-widget-badge");
        this.launcher.append(this.icon, this.badge);
        this.launcher.addEventListener("click", () =>
            this.isOpen ? this.close() : this.open(),
        );

        this.panel = element("div", "chat-widget-panel");
        this.panel.id = `chat-widget-${Math.random().toString(36).slice(2)}`;
        this.panel.setAttribute("role", "dialog");
        this.panel.hidden = true;
        this.launcher.setAttribute("aria-controls", this.panel.id);
        const header = element("header", "chat-widget-header");
        const titles = element("div", "chat-widget-titles");
        this.heading = element("div", "chat-widget-heading");
        this.subheading = element("div", "chat-widget-subheading");
        titles.append(this.heading, this.subheading);
        this.closer = element("button", "chat-widget-close", "×");
        this.closer.type = "button";
        this.closer.addEventListener("click", () => this.close());
        header.append(titles, this.closer);
        this.thread = document.createElement("chat-thread");
        if (this._client) this.thread.client = this._client;
        this.panel.append(header, this.thread);
        this.append(this.panel, this.launcher);
    }

    renderTexts() {
        if (!this.launcher) return;
        const texts = this._texts;
        const heading = this.getAttribute("heading") ?? texts.heading;
        this.heading.textContent = heading;
        this.subheading.textContent = this.getAttribute("subheading") ?? "";
        this.subheading.hidden = !this.subheading.textContent;
        this.panel.setAttribute("aria-label", heading);
        this.launcher.setAttribute(
            "aria-label",
            this.isOpen ? texts.close : texts.open,
        );
        this.closer.setAttribute("aria-label", texts.close);
    }

    renderBadge() {
        if (!this.badge) return;
        const id = this.conversation;
        const unread =
            !this.isOpen && id && this._client?.rooms.has(id)
                ? this._client.room(id).unread
                : 0;
        this.badge.textContent = unread ? String(unread) : "";
        this.badge.hidden = !unread;
        if (unread) {
            this.badge.setAttribute(
                "aria-label",
                format(this._texts.unread, { count: unread }),
            );
        }
    }

    async open() {
        this.setAttribute("open", "");
        this.panel.hidden = false;
        this.launcher.setAttribute("aria-expanded", "true");
        this.renderTexts();
        this.renderBadge();
        let id = this.conversation;
        if (!id && this._client) {
            const invite = (this.getAttribute("with") ?? "")
                .split(/\s+/)
                .filter(Boolean);
            try {
                id = await this._client.createRoom({
                    invite,
                    channel: this.getAttribute("channel") ?? undefined,
                });
            } catch {
                return; // Shown as an empty thread; opening again retries.
            }
            this.started = id;
            remember(this.getAttribute("storage-key"), id);
        }
        if (id) this.thread.setAttribute("conversation", id);
        if (this.thread.store) this.thread.markRead(); // Seen now.
        this.dispatchEvent(
            new CustomEvent("open", { detail: { conversation: id } }),
        );
        this.thread.querySelector(".chat-input")?.focus();
    }

    close() {
        this.removeAttribute("open");
        this.panel.hidden = true;
        this.launcher.setAttribute("aria-expanded", "false");
        this.renderTexts();
        this.renderBadge();
        this.launcher.focus();
        this.dispatchEvent(new Event("close"));
    }
}

if (!customElements.get("chat-widget")) {
    customElements.define("chat-widget", ChatWidget);
}
