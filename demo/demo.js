/**
 * An agent's inbox on one in-memory homeserver — a chatbot that streams its
 * answers and offers quick replies, a WhatsApp chat with receipts whose
 * 24-hour window closes, and an internal chat — and, on another, a site's
 * visitor with the "contact us" widget. Same <chat-thread>, different
 * capabilities.
 */
import "../src/django_chat_ui/static/django_chat_ui/chat-inbox.js";
import "../src/django_chat_ui/static/django_chat_ui/chat-widget.js";
import { ChatClient } from "../src/django_chat_ui/static/django_chat_ui/client.js";
import { FakeHomeserver } from "../src/django_chat_ui/static/django_chat_ui/homeserver.js";
import {
    BUTTONS,
    DELIVERED,
} from "../src/django_chat_ui/static/django_chat_ui/matrix.js";

const me = { id: "@rodolfo:demo", kind: "agent", name: "Rodolfo" };
const bot = { id: "@assistant:demo", kind: "bot", name: "Assistant" };
const anna = {
    id: "@anna:demo",
    kind: "contact",
    name: "Anna Smith",
    handle: "+1 555 0100",
};
const lucy = { id: "@lucy:demo", kind: "user", name: "Lucy Martin" };
const minutesAgo = (n) => Date.now() - n * 60000;

/** A text with quick replies, as the server's `content.text()` makes it. */
function withButtons(body, buttons) {
    return {
        msgtype: "m.text",
        body: `${body}\n\n${buttons
            .map((b) => `• ${b.url ? `${b.label}: ${b.url}` : b.label}`)
            .join("\n")}`,
        [BUTTONS]: { body, buttons },
    };
}

const server = new FakeHomeserver({ me });
for (const user of [bot, anna, lucy]) server.addUser(user);
server.addRoom(
    {
        id: "!bot:demo",
        channel: "bot",
        members: [me.id, bot.id],
        capabilities: {
            buttons: true,
            composer: { mode: "free", placeholder: "Ask anything…" },
        },
    },
    [
        {
            sender: bot.id,
            ts: minutesAgo(5),
            content: withButtons("Hi! I'm the assistant. How can I help?", [
                { id: "order", label: "My order" },
                { id: "human", label: "Talk to someone" },
            ]),
        },
    ],
);
server.addRoom(
    {
        id: "!wa:demo",
        channel: "whatsapp",
        members: [me.id, anna.id],
        capabilities: {
            receipts: true,
            typing: true,
            reactions: true,
            replies: true,
            attachments: { types: ["image", "file"] },
            composer: { mode: "free" },
        },
    },
    [
        {
            sender: anna.id,
            ts: minutesAgo(30),
            content: { msgtype: "m.text", body: "Hi, do you have it in M?" },
        },
        {
            sender: me.id,
            ts: minutesAgo(28),
            content: { msgtype: "m.text", body: "Yes! Here's a photo." },
        },
        {
            sender: me.id,
            ts: minutesAgo(28),
            content: {
                msgtype: "m.image",
                body: "Blue T-shirt, size M",
                url: "shirt.svg",
                info: { w: 240, h: 150, mimetype: "image/svg+xml" },
            },
        },
        {
            sender: anna.id,
            ts: minutesAgo(27),
            content: { msgtype: "m.text", body: "Perfect, thanks 🙌" },
        },
    ],
);
const photo = server.rooms.get("!wa:demo").events.at(-3);
server.event("!wa:demo", anna.id, "m.reaction", {
    "m.relates_to": {
        rel_type: "m.annotation",
        event_id: photo.event_id,
        key: "❤️",
    },
});
server.receipt(
    "!wa:demo",
    anna.id,
    server.rooms.get("!wa:demo").events.at(-2).event_id,
);

server.addRoom(
    {
        id: "!team:demo",
        channel: "internal",
        title: "Support team",
        members: [me.id, lucy.id],
        unread: 1,
        capabilities: {
            receipts: true,
            typing: true,
            reactions: { emojis: ["👍", "✅", "👀", "🎉"] },
            replies: true,
            composer: { mode: "free" },
        },
    },
    [
        {
            sender: lucy.id,
            ts: minutesAgo(12),
            content: {
                msgtype: "m.text",
                body: "Can you look at order A-1029? The customer asks about the delivery.",
            },
        },
    ],
);

const answers = {
    order: ["Your order ", "**A-1029** ", "ships today ", "with UPS."],
    human: ["Putting you through ", "to someone ", "in a moment."],
};

server.onAction = (_event, server, button) => {
    server.stream("!bot:demo", bot.id, answers[button?.id] ?? ["OK."]);
    if (button?.id === "order") {
        // A link button: it opens the page, it doesn't answer.
        setTimeout(
            () =>
                server.post(
                    "!bot:demo",
                    bot.id,
                    withButtons("You can follow it here:", [
                        {
                            label: "Track A-1029",
                            url: "https://www.ups.com/track",
                            style: "primary",
                        },
                    ]),
                ),
            1500,
        );
    }
};
server.onMessage = (event) => {
    const room = [...server.rooms.values()].find((r) =>
        r.events.includes(event),
    );
    if (room.id === "!bot:demo") {
        server.stream("!bot:demo", bot.id, [
            "Let me ",
            "check… ",
            "Is it about an order?",
        ]);
    } else if (room.id === "!wa:demo") {
        // WhatsApp: delivered, then read.
        setTimeout(
            () => server.receipt(room.id, anna.id, event.event_id, DELIVERED),
            600,
        );
        setTimeout(
            () => server.receipt(room.id, anna.id, event.event_id),
            1400,
        );
    }
};

const client = new ChatClient({ fetch: server.fetch });
const inbox = document.querySelector("chat-inbox");
inbox.client = client;
await client.start();

// The site's visitor, on its own homeserver: the widget starts a room that
// the assistant greets.
const visitor = { id: "@visitor:demo", kind: "contact", name: "You" };
const site = new FakeHomeserver({ me: visitor });
site.addUser(bot);
site.newRoom = {
    capabilities: {
        buttons: true,
        composer: { mode: "free", placeholder: "Ask us anything…" },
    },
};
site.onStart = (room) => {
    site.join(room, bot.id);
    setTimeout(() => {
        site.post(
            room,
            bot.id,
            withButtons("Hi! How can we help?", [
                { id: "order", label: "My order" },
                { id: "human", label: "Talk to someone" },
            ]),
        );
    }, 300);
};
site.onAction = (event, site, button) => {
    const room = [...site.rooms.values()].find((r) => r.events.includes(event));
    site.stream(room.id, bot.id, answers[button?.id] ?? ["OK."]);
};
site.onMessage = (event) => {
    const room = [...site.rooms.values()].find((r) => r.events.includes(event));
    site.stream(room.id, bot.id, [
        "Thanks, ",
        "someone will ",
        "answer you shortly.",
    ]);
};
const visitorClient = new ChatClient({ fetch: site.fetch });
const widget = document.querySelector("chat-widget");
widget.client = visitorClient;
await visitorClient.start();

// Demo controls, for screenshots and trying it out.
window.demo = {
    server,
    client,
    inbox,
    widget,
    site,
    closeWindow() {
        server.setCapabilities("!wa:demo", {
            composer: {
                mode: "templates",
                reason: "More than 24 hours since Anna's last message: templates only.",
                templates: [
                    {
                        id: "followup",
                        name: "Follow-up",
                        preview: "Hi {{1}}, can we help with anything else?",
                        params: ["name"],
                    },
                ],
            },
        });
    },
};
