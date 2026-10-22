import { describe, expect, it } from "vitest";
import {
    attachmentTypes,
    capability,
    composerMode,
    DEFAULT_REACTIONS,
    mediaType,
    newTxnId,
    reactionEmojis,
} from "../../src/django_chat_ui/static/django_chat_ui/matrix.js";

describe("matrix.js", () => {
    it("reads what a conversation allows", () => {
        const conversation = {
            capabilities: {
                typing: true,
                attachments: { types: ["image"] },
                composer: { mode: "templates" },
            },
        };
        expect(capability(conversation, "typing")).toBe(true);
        expect(capability(conversation, "receipts")).toBe(false);
        expect(capability(null, "typing")).toBe(false);
        expect(composerMode(conversation)).toBe("templates");
        expect(composerMode({})).toBe("free");
        expect(attachmentTypes(conversation)).toEqual(["image"]);
        expect(
            attachmentTypes({ capabilities: { attachments: true } }),
        ).toEqual([]);
        expect(attachmentTypes({})).toEqual([]);
    });

    it("offers reactions", () => {
        expect(reactionEmojis({})).toEqual([]);
        expect(reactionEmojis({ capabilities: { reactions: true } })).toEqual(
            DEFAULT_REACTIONS,
        );
        expect(
            reactionEmojis({ capabilities: { reactions: { emojis: [] } } }),
        ).toEqual(DEFAULT_REACTIONS);
        expect(
            reactionEmojis({ capabilities: { reactions: { emojis: ["✅"] } } }),
        ).toEqual(["✅"]);
    });

    it("chooses a file's message type", () => {
        expect(mediaType("image/png", ["image", "file"])).toBe("m.image");
        expect(mediaType("image/png", ["file"])).toBe("m.file");
        expect(mediaType("application/pdf", ["file"])).toBe("m.file");
        expect(mediaType("audio/ogg", ["image"])).toBe(null);
        expect(mediaType(undefined, ["file"])).toBe("m.file");
    });

    it("makes unique transaction IDs", () => {
        const ids = new Set(Array.from({ length: 50 }, () => newTxnId()));
        expect(ids.size).toBe(50);
    });
});
