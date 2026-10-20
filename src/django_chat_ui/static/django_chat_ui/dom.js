/** Small DOM helpers shared by the components: nodes, never HTML strings. */

export function element(tag, className, text) {
    const node = document.createElement(tag);
    if (className) node.className = className;
    if (text !== undefined && text !== null) node.textContent = String(text);
    return node;
}

/** "%(name)s is typing…" with `{ name: "Ana" }`. */
export function format(template, values) {
    return template.replace(/%\((\w+)\)s/g, (_, key) => values[key] ?? "");
}
