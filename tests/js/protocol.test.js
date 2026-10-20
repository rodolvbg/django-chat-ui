import { describe, expect, it } from "vitest";
import {
    attachmentTypes,
    capability,
    composerMode,
    isNamespaced,
    newId,
    PART_TYPES,
} from "../../src/django_chat_ui/static/django_chat_ui/protocol.js";

describe("protocol", () => {
    it("tells extension names", () => {
        expect(isNamespaced("acme.order")).toBe(true);
        expect(isNamespaced("shop.cart.updated")).toBe(true);
        expect(isNamespaced("text")).toBe(false);
        expect(isNamespaced("message.created")).toBe(false); // reserved
        expect(isNamespaced("Acme.Order")).toBe(false);
        expect(isNamespaced(undefined)).toBe(false);
    });

    it("lists the protocol's part types", () => {
        expect(PART_TYPES).toContain("template");
        expect(PART_TYPES.some(isNamespaced)).toBe(false);
    });

    it("reads capabilities, missing ones off", () => {
        const conversation = {
            capabilities: {
                receipts: true,
                attachments: { types: ["image"] },
                composer: { mode: "templates" },
            },
        };
        expect(capability(conversation, "receipts")).toBe(true);
        expect(capability(conversation, "typing")).toBe(false);
        expect(capability(undefined, "typing")).toBe(false);
        expect(composerMode(conversation)).toBe("templates");
        expect(composerMode({})).toBe("free");
        expect(attachmentTypes(conversation)).toEqual(["image"]);
        expect(attachmentTypes({ capabilities: { attachments: {} } })).toEqual(
            [],
        );
        expect(attachmentTypes({})).toEqual([]);
    });

    it("makes unique ids", () => {
        const ids = new Set(Array.from({ length: 100 }, () => newId("x")));
        expect(ids.size).toBe(100);
        expect([...ids][0]).toMatch(/^x_/);
    });
});
