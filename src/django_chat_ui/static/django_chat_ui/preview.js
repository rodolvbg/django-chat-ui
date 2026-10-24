/** What a message is about, in one line of text. */

import { BUTTONS, CARD, CONTACT } from "./matrix.js";

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

/** One line saying what a message is about: for the inbox's list, and
 * the quote of a reply. `texts` has image, video, audio, voice, location
 * and deleted. */
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
