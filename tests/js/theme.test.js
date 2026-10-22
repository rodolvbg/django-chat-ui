import { afterEach, describe, expect, it, vi } from "vitest";

const MODULE = "../../src/django_chat_ui/static/django_chat_ui/theme.js";

async function fresh() {
    vi.resetModules();
    return import(MODULE);
}

function component(html = "<chat-thread></chat-thread>") {
    document.body.innerHTML = html;
    return document.querySelector("chat-thread, chat-inbox, chat-widget");
}

const flush = () => new Promise((resolve) => setTimeout(resolve, 0));

afterEach(() => {
    document.body.replaceChildren();
    document.body.removeAttribute("style");
    document.body.removeAttribute("class");
    const root = document.documentElement;
    root.removeAttribute("class");
    root.removeAttribute("data-theme");
    root.removeAttribute("style");
    vi.unstubAllGlobals();
    vi.restoreAllMocks();
});

describe("lightness()", () => {
    it("reads the colours browsers compute", async () => {
        const { lightness } = await fresh();
        expect(lightness("rgb(255, 255, 255)")).toBeCloseTo(1);
        expect(lightness("rgb(13, 17, 23)")).toBeLessThan(0.1);
        expect(lightness("rgba(0, 0, 0, 0)")).toBe(null);
        expect(lightness("rgba(255, 255, 255, 0.5)")).toBeCloseTo(1);
        expect(lightness("rgb(255 255 255 / 0)")).toBe(null);
        // Tailwind 4's (oklch), and the other CSS Color 4 spaces.
        expect(lightness("oklch(0.985 0 0)")).toBeCloseTo(0.985);
        expect(lightness("oklch(21% 0.034 264.665)")).toBeCloseTo(0.21);
        expect(lightness("oklch(0.2 0 0 / 0)")).toBe(null);
        expect(lightness("oklch(0.2 0 0 / 0.5)")).toBeCloseTo(0.2);
        expect(lightness("lab(90 0 0)")).toBeCloseTo(0.9);
        expect(lightness("lch(10% 0 0)")).toBeCloseTo(0.1);
        expect(lightness("color(srgb 1 1 1)")).toBeCloseTo(1);
        expect(lightness("color(srgb 0 0 0 / 0)")).toBe(null);
        expect(lightness("color(srgb 0 0 0 / 1)")).toBe(0);
        expect(lightness("transparent")).toBe(null);
        expect(lightness(undefined)).toBe(null);
    });
});

describe("pageTheme()", () => {
    it("follows the closest data-theme or class around", async () => {
        const { pageTheme } = await fresh();
        const root = document.documentElement;
        const thread = component(
            '<div id="box"><chat-thread data-theme="light"></chat-thread></div>',
        );
        root.dataset.theme = "dark"; // Django's admin
        expect(pageTheme(thread)).toBe("dark"); // (its own is chat.css's)
        root.dataset.theme = "auto";
        root.classList.add("dark"); // Tailwind, Unfold
        expect(pageTheme(thread)).toBe("dark");
        document.getElementById("box").classList.add("light");
        expect(pageTheme(thread)).toBe("light");
        document.getElementById("box").dataset.theme = "dark";
        expect(pageTheme(thread)).toBe("dark");
    });

    it("else, the background behind it", async () => {
        const { pageTheme } = await fresh();
        const thread = component(
            '<div id="card"><chat-thread></chat-thread></div>',
        );
        document.body.style.backgroundColor = "rgb(23, 23, 23)";
        expect(pageTheme(thread)).toBe("dark");
        document.getElementById("card").style.backgroundColor = "#fff";
        expect(pageTheme(thread)).toBe("light");
    });

    it("else, the page's color-scheme, or nothing: the system's", async () => {
        const { pageTheme } = await fresh();
        const thread = component();
        const style = vi.spyOn(window, "getComputedStyle");
        const scheme = (value) =>
            style.mockImplementation(() => ({
                backgroundColor: "rgba(0, 0, 0, 0)",
                colorScheme: value,
            }));
        scheme("dark");
        expect(pageTheme(thread)).toBe("dark");
        scheme("only light");
        expect(pageTheme(thread)).toBe("light");
        scheme("light dark");
        expect(pageTheme(thread)).toBe(null);
        scheme("normal");
        expect(pageTheme(thread)).toBe(null);
        scheme(undefined);
        expect(pageTheme(thread)).toBe(null);
    });
});

describe("followPageTheme()", () => {
    it("marks the component, and follows a switch of theme", async () => {
        const { followPageTheme, unfollowPageTheme } = await fresh();
        const thread = component();
        followPageTheme(thread);
        expect(thread.hasAttribute("data-page-theme")).toBe(false);
        document.documentElement.classList.add("dark");
        await flush();
        expect(thread.dataset.pageTheme).toBe("dark");
        document.documentElement.dataset.theme = "light";
        document.documentElement.classList.remove("dark");
        await flush();
        expect(thread.dataset.pageTheme).toBe("light");
        document.body.style.backgroundColor = "rgb(0, 0, 0)";
        document.documentElement.removeAttribute("data-theme");
        await flush();
        expect(thread.dataset.pageTheme).toBe("dark");

        unfollowPageTheme(thread);
        document.documentElement.classList.add("light");
        await flush();
        expect(thread.dataset.pageTheme).toBe("dark"); // Not followed now.
        window.dispatchEvent(new Event("load"));
    });

    it("leaves a thread inside an inbox or a widget to them", async () => {
        const { followPageTheme } = await fresh();
        document.documentElement.classList.add("dark");
        component(
            "<chat-inbox><div><chat-thread></chat-thread></div></chat-inbox>",
        );
        const thread = document.querySelector("chat-thread");
        followPageTheme(thread);
        expect(thread.hasAttribute("data-page-theme")).toBe(false);
        followPageTheme(document.querySelector("chat-inbox"));
        expect(document.querySelector("chat-inbox").dataset.pageTheme).toBe(
            "dark",
        );
    });

    it("follows the system's theme changing, and a body that comes later", async () => {
        const listeners = [];
        vi.stubGlobal(
            "matchMedia",
            vi.fn(() => ({
                addEventListener: (_type, listener) => listeners.push(listener),
            })),
        );
        const { followPageTheme } = await fresh();
        const thread = component();
        const body = document.body;
        body.remove();
        followPageTheme(thread);
        document.documentElement.append(body);
        document.dispatchEvent(new Event("DOMContentLoaded"));
        body.classList.add("dark");
        await flush();
        expect(thread.dataset.pageTheme).toBe("dark");
        body.classList.remove("dark");
        expect(listeners).toHaveLength(1);
        listeners[0]();
        expect(thread.hasAttribute("data-page-theme")).toBe(false);
    });
});
