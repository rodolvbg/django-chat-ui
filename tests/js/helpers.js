import "../../src/django_chat_ui/static/django_chat_ui/chat-thread.js";
import { ChatClient } from "../../src/django_chat_ui/static/django_chat_ui/client.js";
import { FakeHomeserver } from "../../src/django_chat_ui/static/django_chat_ui/homeserver.js";
import { BUTTONS } from "../../src/django_chat_ui/static/django_chat_ui/matrix.js";

export const ME = { id: "@me:demo", kind: "user", name: "Rodolfo" };
export const BOT = { id: "@bot:demo", kind: "bot", name: "Asistente" };
export const ANA = {
    id: "@ana:demo",
    kind: "contact",
    name: "Ana García",
    handle: "+34 600 000 000",
};

const clients = [];

/** Let the in-memory "network" deliver everything pending. */
export async function flush(rounds = 30) {
    for (let i = 0; i < rounds; i += 1) {
        await new Promise((resolve) => setTimeout(resolve, 0));
    }
}

/** Stop every client the tests started (their syncs). */
export function stopAll() {
    for (const client of clients.splice(0)) client.stop();
}

/** A started client on a fake homeserver with `rooms` (`[room,
 * messages]`), and (with `thread`) a <chat-thread> on that room. */
export async function setup({
    rooms = [],
    thread,
    me = ME,
    users = [BOT, ANA],
    options = {},
} = {}) {
    const server = new FakeHomeserver({ me });
    for (const user of users) server.addUser(user);
    for (const [room, messages] of rooms) server.addRoom(room, messages);
    const client = new ChatClient({
        fetch: server.fetch,
        timeout: 20,
        retry: 5,
        ...options,
    });
    clients.push(client);
    await client.start();
    let element = null;
    if (thread) {
        element = document.createElement("chat-thread");
        element.setAttribute("conversation", thread);
        document.body.append(element);
        element.client = client;
    }
    await flush();
    return { server, client, thread: element };
}

export function messages(thread) {
    return [...thread.querySelectorAll(".chat-message")];
}

export function text(node) {
    return node.textContent.replace(/\s+/g, " ").trim();
}

export function says(body) {
    return { msgtype: "m.text", body };
}

/** A text with quick replies, as the server's `content.text()` makes it. */
export function withButtons(body, buttons, extra = {}) {
    return {
        msgtype: "m.text",
        body: `${body}\n\n${buttons.map((b) => `• ${b.label}`).join("\n")}`,
        [BUTTONS]: { body, buttons, ...extra },
    };
}
