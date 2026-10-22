/**
 * The Matrix Client-Server API's names (https://spec.matrix.org), and this
 * package's extensions, namespaced under `io.github.rodolvbg.chat`
 * (docs/protocol.md); helpers to read what conversations allow.
 */

export const NS = "io.github.rodolvbg.chat";

/** State events: what a room allows, and what it is. */
export const CAPABILITIES = `${NS}.capabilities`;
export const CONVERSATION = `${NS}.conversation`;
/** The block of an `m.room.member`'s content: kind, handle, avatar, ext. */
export const PARTICIPANT = `${NS}.participant`;
/** Blocks of a message's content. */
export const BUTTONS = `${NS}.buttons`;
export const ACTION = `${NS}.action`;
export const LINK = `${NS}.link`;
export const SYSTEM = `${NS}.system`;
/** Message types of its own. */
export const CARD = `${NS}.card`;
export const TEMPLATE = `${NS}.template`;
export const CONTACT = `${NS}.contact`;
/** Ephemeral events: a message being written, a message's status. */
export const STREAM = `${NS}.stream`;
export const STATUS = `${NS}.status`;
/** A receipt type: the channel delivered it. */
export const DELIVERED = `${NS}.delivered`;

export const HTML = "org.matrix.custom.html";

/** A conversation's capability: missing ones are off. */
export function capability(conversation, name) {
    return conversation?.capabilities?.[name] ?? false;
}

/** What the composer allows: `free`, `templates`, `actions`, `closed`, or
 * an extension's mode (which the thread treats as `closed`). */
export function composerMode(conversation) {
    return conversation?.capabilities?.composer?.mode ?? "free";
}

/** The attachment types the conversation accepts (empty: none). */
export function attachmentTypes(conversation) {
    const attachments = capability(conversation, "attachments");
    return attachments ? (attachments.types ?? []) : [];
}

/** The reactions offered when a conversation doesn't list its own. */
export const DEFAULT_REACTIONS = ["👍", "❤️", "😂", "😮", "😢", "🙏"];

/** The emojis to react with; empty: no reactions here. */
export function reactionEmojis(conversation) {
    const reactions = capability(conversation, "reactions");
    if (!reactions) return [];
    return Array.isArray(reactions.emojis) && reactions.emojis.length
        ? reactions.emojis
        : DEFAULT_REACTIONS;
}

/** The message type of a file, for a conversation that takes `types`. */
export function mediaType(mime, types) {
    const kind = String(mime ?? "").split("/")[0];
    const wanted = ["image", "video", "audio"].includes(kind) ? kind : "file";
    if (types.includes(wanted)) return `m.${wanted}`;
    return types.includes("file") ? "m.file" : null;
}

let counter = 0;

/** A unique transaction ID. */
export function newTxnId() {
    counter += 1;
    const random = Math.random().toString(36).slice(2, 8);
    return `t${Date.now().toString(36)}${counter}${random}`;
}
