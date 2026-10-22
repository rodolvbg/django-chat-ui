/**
 * The components follow the theme of the page around them, light or dark,
 * not only the system's: Django's admin with its dark theme chosen, Unfold
 * or a Tailwind site with its "dark" class, show them dark whatever the
 * system says (and light the other way round).
 *
 * The page's theme, the first that says it:
 *   1. the closest element around with data-theme="light"/"dark" (Django's
 *      admin), or the class "light"/"dark" (Tailwind, Unfold);
 *   2. the background of the closest element around that has one, by its
 *      lightness (Unfold's light theme has no class: its page is light);
 *   3. the page's color-scheme, if it's only "light" or only "dark";
 *   4. else, none: the system's (prefers-color-scheme, in chat.css).
 *
 * It's set as data-page-theme on each component that isn't inside another,
 * and kept up to date when <html> or <body> change their class, data-theme
 * or style (a theme switch), or the system its theme. A component's own
 * data-theme wins over it.
 */

const followed = new Set();
let watching = false;

/** The lightness (0–1) of a computed colour, or null: transparent, or a
 * format it doesn't read. */
export function lightness(color) {
    const value = String(color ?? "").trim();
    let match = /^rgba?\(([^)]+)\)$/i.exec(value);
    if (match) {
        const [r, g, b, a = "1"] = match[1].split(/[\s,/]+/).filter(Boolean);
        if (Number.parseFloat(a) === 0) return null;
        // Relative luminance's weights; enough to tell light from dark.
        return (0.2126 * r + 0.7152 * g + 0.0722 * b) / 255;
    }
    match =
        /^(oklch|oklab|lch|lab)\(\s*([\d.]+)(%?)([^/)]*)(?:\/\s*([\d.]+)(%?))?\s*\)$/i.exec(
            value,
        );
    if (match) {
        if (match[5] !== undefined && Number.parseFloat(match[5]) === 0) {
            return null;
        }
        const l = Number.parseFloat(match[2]);
        const scale = match[3] || /^(lch|lab)$/i.test(match[1]) ? 100 : 1;
        return l / scale;
    }
    match =
        /^color\(srgb\s+([\d.]+)\s+([\d.]+)\s+([\d.]+)(?:\s*\/\s*([\d.]+))?\)$/i.exec(
            value,
        );
    if (match) {
        if (match[4] !== undefined && Number.parseFloat(match[4]) === 0) {
            return null;
        }
        const [, r, g, b] = match.map(Number.parseFloat);
        return 0.2126 * r + 0.7152 * g + 0.0722 * b;
    }
    return null;
}

/** The theme of the page around `element`: "light", "dark", or null (the
 * system's). */
export function pageTheme(element) {
    for (let node = element.parentElement; node; node = node.parentElement) {
        const theme = node.getAttribute("data-theme");
        if (theme === "light" || theme === "dark") return theme;
        if (node.classList.contains("dark")) return "dark";
        if (node.classList.contains("light")) return "light";
    }
    for (let node = element.parentElement; node; node = node.parentElement) {
        const value = lightness(getComputedStyle(node).backgroundColor);
        if (value !== null) return value < 0.5 ? "dark" : "light";
    }
    const scheme = getComputedStyle(document.documentElement).colorScheme ?? "";
    const dark = /\bdark\b/.test(scheme);
    const light = /\blight\b/.test(scheme);
    if (dark !== light) return dark ? "dark" : "light";
    return null;
}

function apply(element) {
    const theme = pageTheme(element);
    if (theme) element.setAttribute("data-page-theme", theme);
    else element.removeAttribute("data-page-theme");
}

function update() {
    for (const element of followed) apply(element);
}

function watch() {
    if (watching) return;
    watching = true;
    const observer = new MutationObserver(update);
    const options = {
        attributes: true,
        attributeFilter: ["class", "data-theme", "style"],
    };
    observer.observe(document.documentElement, options);
    const body = () => {
        if (document.body) observer.observe(document.body, options);
    };
    body();
    document.addEventListener("DOMContentLoaded", body);
    // Once the stylesheets are in, the backgrounds are the page's.
    window.addEventListener("load", update);
    window
        .matchMedia?.("(prefers-color-scheme: dark)")
        .addEventListener?.("change", update);
}

/** Follow the page's theme on `element`: unless it's inside another
 * component, whose theme it takes. */
export function followPageTheme(element) {
    if (element.parentElement?.closest("chat-inbox, chat-widget")) return;
    followed.add(element);
    apply(element);
    watch();
}

export function unfollowPageTheme(element) {
    followed.delete(element);
}
