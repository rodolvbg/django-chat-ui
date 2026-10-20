/**
 * Connects the page's components to the Django backend, with the
 * configuration {% chat_ui %} writes (a JSON data block: no inline script).
 *
 * Every <chat-thread>, <chat-inbox> and <chat-widget> in the page gets the
 * client, the translated texts and the uploader. For components added
 * later, or to talk to the client:
 *
 *   import { attach, client } from ".../django_chat_ui/boot.js";
 *   attach(document.querySelector("chat-thread"));
 */

import "./chat-inbox.js";
import "./chat-widget.js";
import { ChatClient } from "./client.js";
import { HttpTransport, httpUploader } from "./transports/http.js";

function readConfig() {
    const node = document.getElementById("chat-ui-config");
    if (!node) return null;
    try {
        return JSON.parse(node.textContent);
    } catch {
        return null;
    }
}

export const config = readConfig();

export const client = config
    ? new ChatClient(
          new HttpTransport({
              events: config.events,
              commands: config.commands,
              csrfToken: config.csrfToken,
              poll: config.transport === "polling" ? config.poll : 0,
          }),
      )
    : null;

const uploader = config
    ? httpUploader({ uploads: config.uploads, csrfToken: config.csrfToken })
    : null;

/** Give a component the client, its texts and the uploader. */
export function attach(element) {
    if (!client) return;
    const texts = config.texts ?? {};
    const own = {
        "CHAT-INBOX": texts.inbox,
        "CHAT-WIDGET": texts.widget,
    }[element.tagName];
    element.texts = { ...texts.thread, ...own };
    element.uploader = uploader;
    element.client = client;
}

if (client) {
    for (const element of document.querySelectorAll(
        "chat-thread, chat-inbox, chat-widget",
    )) {
        // The thread of an inbox or a widget is theirs to set up.
        if (!element.parentElement?.closest("chat-inbox, chat-widget")) {
            attach(element);
        }
    }
    client.connect().catch((error) => {
        console.error("django-chat-ui: can't connect.", error);
    });
}
