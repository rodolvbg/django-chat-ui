/**
 * The chat UI protocol (docs/protocol.md): its names, and helpers to read
 * what conversations allow.
 */

export const PROTOCOL_VERSIONS = ["1.0"];

/** Part types of the protocol (section 5.2); others are namespaced. */
export const PART_TYPES = [
    "text",
    "image",
    "video",
    "audio",
    "file",
    "location",
    "contact",
    "buttons",
    "link",
    "card",
    "system",
    "template",
];

/** Words a namespace can't be (section 3.2). */
export const RESERVED = [
    "message",
    "conversation",
    "participant",
    "typing",
    "read",
    "presence",
    "action",
    "hello",
    "ready",
    "ack",
    "error",
    "history",
    "chat",
];

const NAMESPACED = /^[a-z][a-z0-9_-]*(\.[a-z0-9_-]+)+$/;

/** Whether `name` is an extension's: `<namespace>.<name>`. */
export function isNamespaced(name) {
    return (
        typeof name === "string" &&
        NAMESPACED.test(name) &&
        !RESERVED.includes(name.split(".")[0])
    );
}

/** A conversation's capability (section 6.1): missing ones are off. */
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

let counter = 0;

/** A unique id for commands and optimistic messages. */
export function newId(prefix) {
    counter += 1;
    const random = Math.random().toString(36).slice(2, 8);
    return `${prefix}_${Date.now().toString(36)}${counter}${random}`;
}
