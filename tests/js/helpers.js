import { ChatClient } from "../../src/django_chat_ui/static/django_chat_ui/client.js";
import "../../src/django_chat_ui/static/django_chat_ui/chat-thread.js";
import {
    FakeServer,
    MemoryTransport,
} from "../../src/django_chat_ui/static/django_chat_ui/transports/memory.js";

export const ME = { id: "p_me", kind: "user", name: "Rodolfo" };

/** Let the in-memory "network" deliver everything pending. */
export async function flush(rounds = 10) {
    for (let i = 0; i < rounds; i += 1) {
        await new Promise((resolve) => setTimeout(resolve, 0));
    }
}

/** A connected client, its fake server, and (with `thread`) a <chat-thread>
 * on `conversation`. */
export async function setup({ conversations = [], thread, me = ME } = {}) {
    const server = new FakeServer({ me });
    for (const [conversation, messages] of conversations) {
        server.addConversation(conversation, messages);
    }
    const client = new ChatClient(new MemoryTransport(server));
    await client.connect();
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
