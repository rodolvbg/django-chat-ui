import { describe, expect, it } from "vitest";
import {
    element,
    format,
} from "../../src/django_chat_ui/static/django_chat_ui/dom.js";

describe("dom.js", () => {
    it("makes nodes and fills texts", () => {
        expect(element("p", "a", 1).outerHTML).toBe('<p class="a">1</p>');
        expect(element("p").outerHTML).toBe("<p></p>");
        expect(format("%(name)s is %(what)s", { name: "Ana" })).toBe("Ana is ");
    });
});
