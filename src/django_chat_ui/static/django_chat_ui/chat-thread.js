/**
 * <chat-thread>: one conversation of the chat UI protocol — its messages,
 * who is typing, and a composer that follows the conversation's
 * capabilities (free text, templates only, buttons only, closed).
 *
 *   <chat-thread conversation="conv_1"></chat-thread>
 *   thread.client = new ChatClient(transport);   // then client.connect()
 *
 * Properties:
 *   client     a ChatClient (client.js)
 *   texts      the interface's texts, merged over TEXTS (translations)
 *   uploader   async (file) => part: makes attachments possible
 *
 * It renders with DOM nodes and classes (chat.css), no HTML strings, so it
 * works under a strict Content Security Policy.
 */

import { element, format } from "./dom.js";
import { renderPart } from "./parts.js";
import { attachmentTypes, capability, composerMode } from "./protocol.js";

export const TEXTS = {
    placeholder: "Write a message…",
    send: "Send",
    attach: "Attach",
    retry: "Retry",
    failed: "Not sent",
    edited: "edited",
    earlier: "Load earlier messages",
    typingOne: "%(name)s is typing…",
    typingMany: "Several people are typing…",
    actionsOnly: "Choose one of the options above.",
    closed: "This conversation is closed.",
    template: "Template",
    sendTemplate: "Send template",
    unsupported: "This content can't be shown here.",
    sending: "Sending",
    sent: "Sent",
    delivered: "Delivered",
    read: "Read",
    log: "Messages",
};

const STATUS_MARKS = { sending: "🕓", sent: "✓", delivered: "✓✓", read: "✓✓" };

export class ChatThread extends HTMLElement {
    constructor() {
        super();
        this._client = null;
        this._store = null;
        this._texts = TEXTS;
        this.uploader = null;
        this.onChange = () => this.render();
        this.typingTimer = null;
    }

    static get observedAttributes() {
        return ["conversation"];
    }

    get client() {
        return this._client;
    }

    set client(client) {
        this._client = client;
        this.bind();
    }

    get texts() {
        return this._texts;
    }

    set texts(texts) {
        this._texts = { ...TEXTS, ...texts };
        this.render();
    }

    get store() {
        return this._store;
    }

    connectedCallback() {
        if (!this.shell) this.build();
        this.bind();
    }

    disconnectedCallback() {
        this._store?.removeEventListener("change", this.onChange);
    }

    attributeChangedCallback() {
        this.bind();
    }

    bind() {
        const id = this.getAttribute("conversation");
        if (!this._client || !id || !this.isConnected) return;
        if (!this.shell) this.build();
        this._store?.removeEventListener("change", this.onChange);
        this._store = this._client.conversation(id);
        this._store.addEventListener("change", this.onChange);
        this.render();
        this.open();
    }

    /** Subscribe to the conversation, once the client has a session. */
    open() {
        const client = this._client;
        const store = this._store;
        if (store.opened) return;
        if (!client.me) {
            client.addEventListener("ready", () => this.open(), { once: true });
            return;
        }
        store.opened = true;
        client.open(store.id).catch(() => {
            store.opened = false;
        });
    }

    // Layout ---------------------------------------------------------------

    build() {
        this.shell = element("div", "chat-thread");
        this.log = element("div", "chat-log");
        this.log.setAttribute("role", "log");
        this.log.setAttribute("aria-live", "polite");
        this.earlier = element("button", "chat-earlier");
        this.earlier.type = "button";
        this.earlier.addEventListener("click", () => this.loadEarlier());
        this.list = element("div", "chat-messages");
        this.log.append(this.earlier, this.list);
        this.typingLine = element("div", "chat-typing");
        this.typingLine.setAttribute("aria-live", "polite");
        this.composer = element("form", "chat-composer");
        this.composer.addEventListener("submit", (event) => {
            event.preventDefault();
            this.submit();
        });
        this.shell.append(this.log, this.typingLine, this.composer);
        this.append(this.shell);
    }

    render() {
        if (!this.shell || !this._store) return;
        const atBottom =
            this.log.scrollHeight - this.log.scrollTop - this.log.clientHeight <
            40;
        this.log.setAttribute("aria-label", this._texts.log);
        this.renderEarlier();
        this.renderMessages();
        this.renderTyping();
        this.renderComposer();
        if (atBottom) this.log.scrollTop = this.log.scrollHeight;
        this.markRead();
    }

    /** Tell the server the latest message from others has been seen. */
    markRead() {
        const me = this._client.me?.id;
        // The client's own messages (pending ones too) aren't "read".
        const last = this._store.messages.findLast(
            (message) => message.author !== me,
        );
        if (!last || last.id === this.readSent || document.hidden) return;
        this.readSent = last.id;
        this._client.read(this._store.id, last.id).catch(() => {});
    }

    renderEarlier() {
        const conversation = this._store.conversation;
        this.earlier.hidden = !(
            capability(conversation, "history") && this._store.more
        );
        this.earlier.textContent = this._texts.earlier;
    }

    renderMessages() {
        const store = this._store;
        const participants = store.participants;
        const me = this._client.me?.id;
        const receipts = capability(store.conversation, "receipts");
        const nodes = [];
        let previous = null;
        for (const message of store.messages) {
            nodes.push(
                this.renderMessage(message, {
                    me,
                    participants,
                    receipts,
                    continued:
                        previous?.author === message.author &&
                        !this.isSystem(message, participants),
                }),
            );
            previous = message;
        }
        this.list.replaceChildren(...nodes);
    }

    isSystem(message, participants) {
        return (
            !message.author ||
            participants.get(message.author)?.kind === "system" ||
            message.parts.every((part) => part.type === "system")
        );
    }

    renderMessage(message, { me, participants, receipts, continued }) {
        const author = participants.get(message.author);
        const own = message.author !== undefined && message.author === me;
        const system = this.isSystem(message, participants);
        const kind = system ? "system" : own ? "own" : author?.kind ?? "contact";
        const node = element("article", `chat-message chat-message--${kind}`);
        node.dataset.id = message.id;
        if (continued) node.classList.add("chat-message--continued");
        if (message.streaming) node.classList.add("chat-message--streaming");
        if (message.status) node.dataset.status = message.status;

        if (!own && !system && !continued && author?.name) {
            node.append(element("div", "chat-author", author.name));
        }
        const bubble = element("div", "chat-bubble");
        const context = {
            message,
            store: this._store,
            client: this._client,
            texts: this._texts,
            act: (button) => this.act(message, button),
        };
        for (const part of message.parts) {
            const rendered = renderPart(part, context);
            rendered.classList?.add("chat-part");
            bubble.append(rendered);
        }
        node.append(bubble);
        if (!system) node.append(this.renderMeta(message, own, receipts));
        return node;
    }

    renderMeta(message, own, receipts) {
        const meta = element("div", "chat-meta");
        if (message.createdAt) {
            const time = element("time", "chat-time");
            time.dateTime = message.createdAt;
            time.textContent = new Date(message.createdAt).toLocaleTimeString(
                document.documentElement.lang || undefined,
                { hour: "2-digit", minute: "2-digit" },
            );
            meta.append(time);
        }
        if (message.editedAt) {
            meta.append(element("span", "chat-edited", this._texts.edited));
        }
        if (own && message.status === "failed") {
            meta.append(
                element(
                    "span",
                    "chat-status chat-status--failed",
                    message.error?.message ?? this._texts.failed,
                ),
            );
            const retry = element("button", "chat-retry", this._texts.retry);
            retry.type = "button";
            retry.addEventListener("click", () =>
                this._client
                    .retry(this._store.id, message.clientId)
                    .catch(() => {}),
            );
            meta.append(retry);
        } else if (own && message.status && (receipts || message.status === "sending")) {
            const status = element(
                "span",
                `chat-status chat-status--${message.status}`,
                STATUS_MARKS[message.status] ?? "",
            );
            status.title = this._texts[message.status] ?? message.status;
            status.setAttribute("aria-label", status.title);
            meta.append(status);
        }
        return meta;
    }

    renderTyping() {
        const me = this._client.me?.id;
        const others = [...this._store.typing].filter((id) => id !== me);
        const names = others.map(
            (id) => this._store.participants.get(id)?.name ?? "",
        );
        this.typingLine.textContent =
            others.length === 0
                ? ""
                : others.length === 1
                  ? format(this._texts.typingOne, { name: names[0] })
                  : this._texts.typingMany;
    }

    // Composer -------------------------------------------------------------

    renderComposer() {
        const conversation = this._store.conversation;
        const mode = composerMode(conversation);
        const key = JSON.stringify([
            mode,
            conversation.capabilities?.composer,
            conversation.capabilities?.attachments,
            Boolean(this.uploader),
            this._texts,
        ]);
        if (this.composerKey === key) return; // Keep what's being typed.
        this.composerKey = key;
        this.composer.dataset.mode = mode;
        if (mode === "free") {
            this.composer.replaceChildren(...this.freeComposer(conversation));
        } else if (mode === "templates") {
            this.composer.replaceChildren(...this.templateComposer(conversation));
        } else {
            const note = element(
                "div",
                "chat-composer-note",
                mode === "actions"
                    ? this._texts.actionsOnly
                    : (conversation.capabilities?.composer?.reason ??
                          this._texts.closed),
            );
            this.composer.replaceChildren(note);
        }
    }

    freeComposer(conversation) {
        const composer = conversation.capabilities?.composer ?? {};
        const input = element("textarea", "chat-input");
        input.name = "text";
        input.rows = 1;
        input.placeholder = composer.placeholder ?? this._texts.placeholder;
        input.setAttribute("aria-label", input.placeholder);
        if (composer.maxLength) input.maxLength = composer.maxLength;
        input.addEventListener("keydown", (event) => {
            if (event.key === "Enter" && !event.shiftKey && !event.isComposing) {
                event.preventDefault();
                this.submit();
            }
        });
        input.addEventListener("input", () => this.typed());
        this.input = input;
        const nodes = [];
        const types = attachmentTypes(conversation);
        if (types.length && this.uploader) {
            const file = element("input", "chat-file-input");
            file.type = "file";
            file.hidden = true;
            file.accept = types
                .map((type) => ({ image: "image/*", video: "video/*", audio: "audio/*" })[type] ?? "")
                .filter(Boolean)
                .join(",");
            file.addEventListener("change", () => this.attach(file));
            const button = element("button", "chat-attach", this._texts.attach);
            button.type = "button";
            button.addEventListener("click", () => file.click());
            nodes.push(file, button);
        }
        const send = element("button", "chat-send", this._texts.send);
        send.type = "submit";
        nodes.push(input, send);
        return nodes;
    }

    templateComposer(conversation) {
        const templates = conversation.capabilities?.composer?.templates ?? [];
        const select = element("select", "chat-template");
        select.name = "template";
        select.setAttribute("aria-label", this._texts.template);
        for (const template of templates) {
            const option = element("option", null, template.name ?? template.id);
            option.value = template.id;
            select.append(option);
        }
        const params = element("div", "chat-template-params");
        const preview = element("div", "chat-template-preview");
        const refresh = () => {
            const template = templates.find((item) => item.id === select.value);
            params.replaceChildren(
                ...(template?.params ?? []).map((name) => {
                    const input = element("input", "chat-template-param");
                    input.name = name;
                    input.placeholder = name;
                    input.setAttribute("aria-label", name);
                    input.addEventListener("input", () => {
                        preview.textContent = this.templateText(template, params);
                    });
                    return input;
                }),
            );
            preview.textContent = template ? this.templateText(template, params) : "";
        };
        select.addEventListener("change", refresh);
        refresh();
        const reason = conversation.capabilities?.composer?.reason;
        const send = element("button", "chat-send", this._texts.sendTemplate);
        send.type = "submit";
        return [
            ...(reason ? [element("div", "chat-composer-note", reason)] : []),
            select,
            params,
            preview,
            send,
        ];
    }

    templateValues(params) {
        return Object.fromEntries(
            [...params.querySelectorAll("input")].map((input) => [
                input.name,
                input.value,
            ]),
        );
    }

    /** A template's text with its params: {{1}}, {{2}}… in order, or
     * {{name}}. */
    templateText(template, params) {
        const values = this.templateValues(params);
        const names = template.params ?? [];
        return (template.preview ?? "").replace(/\{\{(\w+)\}\}/g, (match, key) => {
            const name = /^\d+$/.test(key) ? names[Number(key) - 1] : key;
            return values[name] || match;
        });
    }

    submit() {
        const conversation = this._store.conversation;
        const mode = composerMode(conversation);
        if (mode === "free") {
            const text = this.input.value.trim();
            if (!text) return;
            this.input.value = "";
            this.stopTyping();
            this.send([{ type: "text", text }]);
        } else if (mode === "templates") {
            const templates = conversation.capabilities.composer.templates ?? [];
            const select = this.composer.querySelector("select");
            const template = templates.find((item) => item.id === select.value);
            if (!template) return;
            const params = this.composer.querySelector(".chat-template-params");
            this.send([
                {
                    type: "template",
                    template: template.id,
                    params: this.templateValues(params),
                    fallback: this.templateText(template, params),
                },
            ]);
        }
    }

    send(parts) {
        this._client.send(this._store.id, parts).catch(() => {
            // Shown on the message itself ("failed", with Retry).
        });
    }

    async attach(input) {
        const [file] = input.files ?? [];
        if (!file) return;
        input.value = "";
        const part = await this.uploader(file);
        if (part) this.send([part]);
    }

    act(message, button) {
        message.ext = { ...message.ext, chat: { used: button.id } };
        this._store.changed();
        this._client
            .action(this._store.id, message.id, button.id)
            .catch(() => {});
    }

    typed() {
        if (!capability(this._store.conversation, "typing")) return;
        if (!this.typingTimer) {
            this._client.typing(this._store.id, true).catch(() => {});
        } else {
            clearTimeout(this.typingTimer);
        }
        this.typingTimer = setTimeout(() => this.stopTyping(), 3000);
    }

    stopTyping() {
        if (!this.typingTimer) return;
        clearTimeout(this.typingTimer);
        this.typingTimer = null;
        this._client.typing(this._store.id, false).catch(() => {});
    }

    async loadEarlier() {
        const before = this.log.scrollHeight - this.log.scrollTop;
        await this._client.history(this._store.id).catch(() => {});
        // Keep the messages that were in view where they were.
        this.log.scrollTop = this.log.scrollHeight - before;
    }
}

if (!customElements.get("chat-thread")) {
    customElements.define("chat-thread", ChatThread);
}
