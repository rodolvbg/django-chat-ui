/**
 * <chat-thread>: one conversation — a Matrix room: its messages, who is
 * typing, and a composer that follows the conversation's capabilities (free
 * text, templates only, buttons only, closed).
 *
 *   <chat-thread conversation="!1:example.com"></chat-thread>
 *   thread.client = new ChatClient({ baseUrl });   // then client.start()
 *
 * Properties:
 *   client     a ChatClient (client.js)
 *   texts      the interface's texts, merged over TEXTS (translations)
 *
 * Files are sent where the conversation takes them (a failed upload
 * dispatches "uploaderror").
 *
 * It renders with DOM nodes and classes (chat.css), no HTML strings, so it
 * works under a strict Content Security Policy.
 */

import { renderContent } from "./content.js";
import { element, format } from "./dom.js";
import {
    attachmentTypes,
    capability,
    composerMode,
    mediaType,
    reactionEmojis,
    SYSTEM,
    TEMPLATE,
} from "./matrix.js";
import { preview } from "./preview.js";
import { followPageTheme, unfollowPageTheme } from "./theme.js";

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
    react: "React",
    you: "You",
    deleted: "Message deleted",
    reply: "Reply",
    replyingTo: "Replying to %(name)s",
    cancelReply: "Cancel the reply",
    replyUnavailable: "A message not loaded",
    image: "Photo",
    video: "Video",
    audio: "Audio",
    voice: "Voice message",
    location: "Location",
};

const HIGHLIGHT_FOR = 1500;

const STATUS_MARKS = { sending: "🕓", sent: "✓", delivered: "✓✓", read: "✓✓" };

export class ChatThread extends HTMLElement {
    constructor() {
        super();
        this._client = null;
        this._store = null;
        this._texts = TEXTS;
        this.onChange = () => this.render();
        this.typingTimer = null;
        /** The message whose reaction picker is open. */
        this.picking = null;
        /** The message the next one answers. */
        this.replying = null;
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
        followPageTheme(this);
        if (!this.shell) this.build();
        this.bind();
    }

    disconnectedCallback() {
        unfollowPageTheme(this);
        this._store?.removeEventListener("change", this.onChange);
    }

    attributeChangedCallback() {
        this.bind();
    }

    bind() {
        const id = this.getAttribute("conversation");
        // Connected, it's built (connectedCallback).
        if (!this._client || !id || !this.isConnected) return;
        this._store?.removeEventListener("change", this.onChange);
        this._store = this._client.room(id);
        this._store.addEventListener("change", this.onChange);
        this.render();
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
        this.replyBar = element("div", "chat-reply-bar");
        this.replyBar.hidden = true;
        this.shell.append(
            this.log,
            this.typingLine,
            this.replyBar,
            this.composer,
        );
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
        this.renderReplyBar();
        this.renderComposer();
        if (atBottom) this.log.scrollTop = this.log.scrollHeight;
        this.markRead();
    }

    /** Tell the server the latest message from others has been seen: not
     * while it's hidden (a closed widget, an inbox showing another). */
    markRead() {
        if (document.hidden || this.closest("[hidden]")) return;
        const me = this._client.me;
        // The client's own messages (pending ones too) aren't "read".
        const last = this._store.messages.findLast(
            (message) => message.sender !== me && !message.streaming,
        );
        if (!last || last.id === this.readSent) return;
        this.readSent = last.id;
        this._client.read(this._store.id, last.id).catch(() => {
            // Told again on the next render.
            if (this.readSent === last.id) this.readSent = null;
        });
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
        const me = this._client.me;
        const conversation = store.conversation;
        const receipts = capability(conversation, "receipts");
        const nodes = [];
        let previous = null;
        for (const message of store.messages) {
            nodes.push(
                this.renderMessage(message, {
                    me,
                    participants,
                    receipts,
                    conversation,
                    continued:
                        previous?.sender === message.sender &&
                        !this.isSystem(message, participants),
                }),
            );
            previous = message;
        }
        const focused = this.focused();
        this.list.replaceChildren(...nodes);
        this.refocus(focused);
    }

    /** What has the focus in the list, to find it again once redrawn. */
    focused() {
        const active = document.activeElement;
        if (!active || active === this.list || !this.list.contains(active)) {
            return null;
        }
        return {
            message: active.closest("[data-id]")?.dataset.id,
            className: active.classList[0],
            emoji: active.dataset.emoji,
        };
    }

    refocus(focused) {
        if (!focused?.message || !focused.className) return;
        const candidates = [
            ...(this.messageNode(focused.message)?.getElementsByClassName(
                focused.className,
            ) ?? []),
        ];
        const same =
            candidates.find((node) => node.dataset.emoji === focused.emoji) ??
            candidates[0];
        same?.focus();
    }

    isSystem(message, participants) {
        return (
            SYSTEM in message.content ||
            participants.get(message.sender)?.kind === "system" ||
            String(message.sender).startsWith("@system:")
        );
    }

    renderMessage(
        message,
        { me, participants, receipts, conversation, continued },
    ) {
        const author = participants.get(message.sender);
        const own = Boolean(message.sender) && message.sender === me;
        const system = this.isSystem(message, participants);
        const kind = system
            ? "system"
            : own
              ? "own"
              : (author?.kind ?? "contact");
        const node = element("article", `chat-message chat-message--${kind}`);
        node.dataset.id = message.id;
        if (continued) node.classList.add("chat-message--continued");
        if (message.streaming) node.classList.add("chat-message--streaming");
        if (message.status) node.dataset.status = message.status;

        if (!own && !system && !continued && author?.name) {
            node.append(element("div", "chat-author", author.name));
        }
        const bubble = element("div", "chat-bubble");
        if (message.replyTo && !system) {
            bubble.append(this.renderQuote(message.replyTo, participants, me));
        }
        if (message.redacted) {
            bubble.append(
                element("div", "chat-part chat-deleted", this._texts.deleted),
            );
        } else {
            const context = {
                message,
                store: this._store,
                client: this._client,
                texts: this._texts,
                media: (uri) => this._client.mediaUrl(uri),
                act: (button) => this.act(message, button),
            };
            const rendered = system
                ? element("div", "chat-system", message.content.body)
                : renderContent(message.content, context);
            rendered.classList?.add("chat-part");
            bubble.append(rendered);
        }
        node.append(bubble);
        if (!system) {
            const reactions = this.renderReactions(
                message,
                me,
                participants,
                conversation,
            );
            if (reactions) node.append(reactions);
            const meta = this.renderMeta(message, own, receipts);
            if (this.reactable(message, conversation).length) {
                meta.append(this.renderReactButton(message));
            }
            if (this.repliable(message, conversation)) {
                meta.append(this.renderReplyButton(message));
            }
            node.append(meta);
        }
        return node;
    }

    /** Whether one can react to this message here, and with what. */
    reactable(message, conversation) {
        const emojis = reactionEmojis(conversation);
        const can =
            emojis.length > 0 &&
            !message.redacted &&
            !message.streaming &&
            !message.id.startsWith("~");
        return can ? emojis : [];
    }

    /** Its reactions (who, on hover), and the picker when it's open: only
     * when there's any, not to take a line under every message. */
    renderReactions(message, me, participants, conversation) {
        const emojis = this.reactable(message, conversation);
        const reactions = message.reactions;
        const open = this.picking === message.id && emojis.length > 0;
        if (!reactions.length && !open) return null;
        const mine = new Set(
            reactions.filter((r) => r.by.includes(me)).map((r) => r.key),
        );
        const row = element("div", "chat-reactions");
        for (const reaction of reactions) {
            const names = reaction.by.map((id) =>
                id === me
                    ? this._texts.you
                    : (participants.get(id)?.name ?? "?"),
            );
            const button = element("button", "chat-reaction");
            button.type = "button";
            button.dataset.emoji = reaction.key;
            button.append(
                element("span", "chat-reaction-emoji", reaction.key),
                element("span", "chat-reaction-count", reaction.by.length),
            );
            button.title = names.join(", ");
            button.setAttribute(
                "aria-label",
                `${reaction.key} ${button.title}`,
            );
            button.setAttribute("aria-pressed", String(mine.has(reaction.key)));
            button.disabled = !emojis.length;
            button.addEventListener("click", () =>
                this.react(message, reaction.key, !mine.has(reaction.key)),
            );
            row.append(button);
        }
        if (open) {
            const picker = element("div", "chat-react-picker");
            picker.setAttribute("role", "group");
            picker.setAttribute("aria-label", this._texts.react);
            picker.addEventListener("keydown", (event) => {
                if (event.key === "Escape") this.pick(null, message.id);
            });
            for (const emoji of emojis) {
                const choice = element("button", "chat-react-choice", emoji);
                choice.type = "button";
                choice.dataset.emoji = emoji;
                choice.setAttribute("aria-pressed", String(mine.has(emoji)));
                choice.addEventListener("click", () => {
                    this.picking = null;
                    this.react(message, emoji, !mine.has(emoji));
                });
                picker.append(choice);
            }
            row.append(picker);
        }
        return row;
    }

    // Replies ----------------------------------------------------------------

    /** Whether one can answer this message here. */
    repliable(message, conversation) {
        return (
            Boolean(capability(conversation, "replies")) &&
            !message.redacted &&
            !message.streaming &&
            !message.id.startsWith("~")
        );
    }

    renderReplyButton(message) {
        const button = element("button", "chat-reply-button", "↩");
        button.type = "button";
        button.title = this._texts.reply;
        button.setAttribute("aria-label", this._texts.reply);
        button.addEventListener("click", () => this.startReply(message.id));
        return button;
    }

    /** Answer `id` with the next message. */
    startReply(id) {
        this.replying = id;
        this.render();
        this.input?.focus();
    }

    cancelReply() {
        this.replying = null;
        this.render();
        this.input?.focus();
    }

    /** Who wrote a message, and what it's about: for quotes. */
    quoted(id, participants, me) {
        const message = this._store.messages.find((m) => m.id === id);
        if (!message) return null;
        const name =
            message.sender === me
                ? this._texts.you
                : (participants.get(message.sender)?.name ?? "");
        return { name, text: preview(message, this._texts) };
    }

    /** The quote of the message `id` answers; to it, when chosen. */
    renderQuote(id, participants, me) {
        const quote = element("button", "chat-quote");
        quote.type = "button";
        const found = this.quoted(id, participants, me);
        if (!found) {
            quote.disabled = true;
            quote.append(
                element(
                    "span",
                    "chat-quote-text",
                    this._texts.replyUnavailable,
                ),
            );
            return quote;
        }
        quote.append(
            element("span", "chat-quote-author", found.name),
            element("span", "chat-quote-text", found.text),
        );
        quote.setAttribute("aria-label", `${found.name}: ${found.text}`);
        quote.addEventListener("click", () => this.reveal(id));
        return quote;
    }

    /** Bring a message into view, marked for a moment. */
    reveal(id) {
        const node = this.messageNode(id);
        if (!node) return;
        node.scrollIntoView?.({ block: "center", behavior: "smooth" });
        node.classList.add("chat-message--highlight");
        setTimeout(
            () => node.classList.remove("chat-message--highlight"),
            HIGHLIGHT_FOR,
        );
    }

    /** "Replying to Ana: …", over the composer, while there's a reply. */
    renderReplyBar() {
        const conversation = this._store.conversation;
        const found =
            this.replying &&
            capability(conversation, "replies") &&
            composerMode(conversation) === "free"
                ? this.quoted(
                      this.replying,
                      this._store.participants,
                      this._client.me,
                  )
                : null;
        this.replyBar.hidden = !found;
        if (!found) {
            this.replyBar.replaceChildren();
            return;
        }
        const label = element(
            "div",
            "chat-reply-label",
            format(this._texts.replyingTo, { name: found.name }),
        );
        const text = element("div", "chat-reply-text", found.text);
        const cancel = element("button", "chat-reply-cancel", "✕");
        cancel.type = "button";
        cancel.title = this._texts.cancelReply;
        cancel.setAttribute("aria-label", this._texts.cancelReply);
        cancel.addEventListener("click", () => this.cancelReply());
        const body = element("div", "chat-reply-body");
        body.append(label, text);
        this.replyBar.replaceChildren(body, cancel);
    }

    /** The button that opens the picker, next to the time. */
    renderReactButton(message) {
        const open = this.picking === message.id;
        const add = element("button", "chat-react", "☺");
        add.type = "button";
        add.title = this._texts.react;
        add.setAttribute("aria-label", this._texts.react);
        add.setAttribute("aria-expanded", String(open));
        add.addEventListener("click", () =>
            this.pick(open ? null : message.id),
        );
        return add;
    }

    /** Open the reaction picker of a message (null: close it), keeping the
     * focus where it makes sense. */
    pick(id, back = this.picking) {
        this.picking = id;
        this.render();
        const node = this.messageNode(id ?? back);
        node?.querySelector(id ? ".chat-react-choice" : ".chat-react")?.focus();
    }

    /** The node of a message in the list. */
    messageNode(id) {
        return [...this.list.children].find((node) => node.dataset.id === id);
    }

    react(message, emoji, active) {
        const client = this._client;
        const done = active
            ? client.react(this._store.id, message.id, emoji)
            : client.unreact(this._store.id, message.id, emoji);
        done.catch(() => {
            // What the server has comes with the next sync.
        });
        this.pick(null, message.id);
    }

    renderMeta(message, own, receipts) {
        const meta = element("div", "chat-meta");
        if (message.createdAt) {
            const time = element("time", "chat-time");
            time.dateTime = new Date(message.createdAt).toISOString();
            time.textContent = new Date(message.createdAt).toLocaleTimeString(
                document.documentElement.lang || undefined,
                { hour: "2-digit", minute: "2-digit" },
            );
            meta.append(time);
        }
        if (message.edited) {
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
                    .retry(this._store.id, message.txnId)
                    .catch(() => {}),
            );
            meta.append(retry);
        } else if (
            own &&
            message.status &&
            (receipts || message.status === "sending")
        ) {
            const status = element(
                "span",
                `chat-status chat-status--${message.status}`,
                STATUS_MARKS[message.status],
            );
            status.title = this._texts[message.status];
            status.setAttribute("aria-label", status.title);
            meta.append(status);
        }
        return meta;
    }

    renderTyping() {
        const me = this._client.me;
        // Those writing a message that shows already aren't "typing".
        const writing = new Set(
            [...this._store.streams.values()].map((stream) => stream.sender),
        );
        const others = [...this._store.typing].filter(
            (id) => id !== me && !writing.has(id),
        );
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
            this._texts,
        ]);
        if (this.composerKey === key) return; // Keep what's being typed.
        this.composerKey = key;
        this.composer.dataset.mode = mode;
        if (mode === "free") {
            this.composer.replaceChildren(...this.freeComposer(conversation));
        } else if (mode === "templates") {
            this.composer.replaceChildren(
                ...this.templateComposer(conversation),
            );
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
            if (
                event.key === "Enter" &&
                !event.shiftKey &&
                !event.isComposing
            ) {
                event.preventDefault();
                this.submit();
            } else if (event.key === "Escape" && this.replying) {
                event.preventDefault();
                this.cancelReply();
            }
        });
        input.addEventListener("input", () => this.typed());
        this.input = input;
        const nodes = [];
        const types = attachmentTypes(conversation);
        if (types.length && this._client.upload) {
            const file = element("input", "chat-file-input");
            file.type = "file";
            file.hidden = true;
            file.accept = types
                .map(
                    (type) =>
                        ({
                            image: "image/*",
                            video: "video/*",
                            audio: "audio/*",
                        })[type] ?? "",
                )
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
            const option = element(
                "option",
                null,
                template.name ?? template.id,
            );
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
                        preview.textContent = this.templateText(
                            template,
                            params,
                        );
                    });
                    return input;
                }),
            );
            preview.textContent = template
                ? this.templateText(template, params)
                : "";
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
        return (template.preview ?? "").replace(
            /\{\{(\w+)\}\}/g,
            (match, key) => {
                const name = /^\d+$/.test(key) ? names[Number(key) - 1] : key;
                return values[name] || match;
            },
        );
    }

    submit() {
        const conversation = this._store.conversation;
        const mode = composerMode(conversation);
        if (mode === "free") {
            const text = this.input.value.trim();
            if (!text) return;
            this.input.value = "";
            this.stopTyping();
            this.send({ msgtype: "m.text", body: text });
        } else if (mode === "templates") {
            const templates =
                conversation.capabilities.composer.templates ?? [];
            const select = this.composer.querySelector("select");
            const template = templates.find((item) => item.id === select.value);
            if (!template) return;
            const params = this.composer.querySelector(".chat-template-params");
            this.send(
                {
                    msgtype: TEMPLATE,
                    body: this.templateText(template, params),
                    [TEMPLATE]: {
                        id: template.id,
                        params: this.templateValues(params),
                    },
                },
                { reply: false },
            );
        }
    }

    /** Send a message; it answers the one being replied to (`reply`), if
     * the conversation takes replies. */
    send(content, { reply = true } = {}) {
        const replyTo =
            reply && capability(this._store.conversation, "replies")
                ? this.replying
                : null;
        if (replyTo) this.replying = null;
        this._client
            .send(this._store.id, content, replyTo ? { replyTo } : {})
            .catch(() => {
                // Shown on the message itself ("failed", with Retry).
            });
    }

    async attach(input) {
        const [file] = input.files;
        if (!file) return;
        input.value = "";
        const types = attachmentTypes(this._store.conversation);
        const msgtype = mediaType(file.type, types);
        let url;
        try {
            if (!msgtype) throw new Error("unsupported");
            url = await this._client.upload(file);
        } catch (error) {
            this.dispatchEvent(
                new CustomEvent("uploaderror", { detail: { file, error } }),
            );
            return;
        }
        const content = {
            msgtype,
            body: file.name,
            url,
            info: { mimetype: file.type, size: file.size },
        };
        if (msgtype === "m.file") content.filename = file.name;
        this.send(content);
    }

    act(message, button) {
        this._client.action(this._store.id, message.id, button).catch(() => {});
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
