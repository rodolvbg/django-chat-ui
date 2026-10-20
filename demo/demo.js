/**
 * An agent's inbox on one in-memory server — a chatbot that streams its
 * answers and offers quick replies, a WhatsApp chat with receipts whose
 * 24-hour window closes, and an internal chat — and, on another, a site's
 * visitor with the "contact us" widget. Same <chat-thread>, different
 * capabilities.
 */
import "../src/django_chat_ui/static/django_chat_ui/chat-inbox.js";
import "../src/django_chat_ui/static/django_chat_ui/chat-widget.js";
import { ChatClient } from "../src/django_chat_ui/static/django_chat_ui/client.js";
import {
    FakeServer,
    MemoryTransport,
} from "../src/django_chat_ui/static/django_chat_ui/transports/memory.js";

const me = { id: "p_me", kind: "agent", name: "Rodolfo" };
const bot = { id: "p_bot", kind: "bot", name: "Assistant" };
const ana = {
    id: "p_ana",
    kind: "contact",
    name: "Anna Smith",
    handle: "+1 555 0100",
};
const lucy = { id: "p_lucy", kind: "user", name: "Lucy Martin" };
const minutesAgo = (n) => new Date(Date.now() - n * 60000).toISOString();

const server = new FakeServer({ me });
server.addConversation(
    {
        id: "conv_bot",
        channel: "bot",
        participants: [me, bot],
        capabilities: {
            streaming: true,
            buttons: true,
            composer: { mode: "free", placeholder: "Ask anything…" },
        },
    },
    [
        {
            id: "b1",
            conversation: "conv_bot",
            author: "p_bot",
            createdAt: minutesAgo(5),
            parts: [
                {
                    type: "text",
                    format: "markdown",
                    text: "Hi! I'm the **assistant**. How can I help?",
                },
                {
                    type: "buttons",
                    buttons: [
                        { id: "order", label: "My order" },
                        { id: "human", label: "Talk to someone" },
                    ],
                    fallback: "My order / Talk to someone",
                },
            ],
        },
    ],
);
server.addConversation(
    {
        id: "conv_wa",
        channel: "whatsapp",
        participants: [me, ana],
        capabilities: {
            receipts: true,
            typing: true,
            attachments: { types: ["image", "file"] },
            composer: { mode: "free" },
        },
    },
    [
        {
            id: "w1",
            conversation: "conv_wa",
            author: "p_ana",
            createdAt: minutesAgo(30),
            parts: [{ type: "text", text: "Hi, do you have it in M?" }],
        },
        {
            id: "w2",
            conversation: "conv_wa",
            author: "p_me",
            createdAt: minutesAgo(28),
            status: "read",
            parts: [{ type: "text", text: "Yes! Here's a photo." }],
        },
        {
            id: "w3",
            conversation: "conv_wa",
            author: "p_me",
            createdAt: minutesAgo(28),
            status: "read",
            parts: [
                {
                    type: "image",
                    url: "shirt.svg",
                    alt: "Blue T-shirt, size M",
                    width: 240,
                    height: 150,
                },
            ],
        },
        {
            id: "w4",
            conversation: "conv_wa",
            author: "p_ana",
            createdAt: minutesAgo(27),
            parts: [{ type: "text", text: "Perfect, thanks 🙌" }],
        },
    ],
);

server.addConversation(
    {
        id: "conv_team",
        channel: "internal",
        title: "Support team",
        participants: [me, lucy],
        unread: 1,
        capabilities: {
            receipts: true,
            typing: true,
            composer: { mode: "free" },
        },
    },
    [
        {
            id: "t1",
            conversation: "conv_team",
            author: "p_lucy",
            createdAt: minutesAgo(12),
            parts: [
                {
                    type: "text",
                    text: "Can you look at order A-1029? The customer asks about the delivery.",
                },
            ],
        },
    ],
);

const answers = {
    order: ["Your order ", "**A-1029** ", "ships today ", "with UPS."],
    human: ["Putting you through ", "to someone ", "in a moment."],
};

async function botSays(chunks, buttons) {
    await server.stream("conv_bot", "p_bot", chunks, {
        parts: [
            { type: "text", format: "markdown", text: chunks.join("") },
            ...(buttons
                ? [
                      {
                          type: "buttons",
                          buttons,
                          fallback: buttons.map((b) => b.label).join(" / "),
                      },
                  ]
                : []),
        ],
    });
}

server.onAction = (data) => {
    // The reply chosen, as the user's message (as WhatsApp shows it).
    const message = server.messages
        .get(data.conversation)
        .find((m) => m.id === data.message);
    const button = message.parts
        .flatMap((part) => part.buttons ?? [])
        .find((b) => b.id === data.button);
    server.post(
        data.conversation,
        me.id,
        [{ type: "text", text: button?.label ?? data.button }],
        { status: "sent" },
    );
    botSays(answers[data.button] ?? ["OK."]);
};
server.onMessage = (message) => {
    if (message.conversation === "conv_bot") {
        botSays(
            ["Let me ", "check… ", "Is it about an order?"],
            [{ id: "order", label: "Yes, an order" }],
        );
    } else if (message.conversation === "conv_wa") {
        // WhatsApp: delivered, then read, then the window closes.
        setTimeout(
            () =>
                server.emit("message.updated", {
                    id: message.id,
                    conversation: "conv_wa",
                    status: "delivered",
                }),
            600,
        );
        setTimeout(
            () =>
                server.emit("message.updated", {
                    id: message.id,
                    conversation: "conv_wa",
                    status: "read",
                }),
            1400,
        );
    }
};

const client = new ChatClient(new MemoryTransport(server));
const inbox = document.querySelector("chat-inbox");
inbox.client = client;
await client.connect();

// The site's visitor, on its own server: the widget starts a conversation
// that the assistant greets.
const visitor = { id: "p_visitor", kind: "user", name: "You" };
const site = new FakeServer({ me: visitor });
site.newConversation = {
    participants: [visitor, bot],
    capabilities: {
        streaming: true,
        buttons: true,
        composer: { mode: "free", placeholder: "Ask us anything…" },
    },
};
site.onStart = (conversation) => {
    setTimeout(() => {
        site.post(conversation.id, bot.id, [
            { type: "text", text: "Hi! How can we help?" },
            {
                type: "buttons",
                buttons: [
                    { id: "order", label: "My order" },
                    { id: "human", label: "Talk to someone" },
                ],
                fallback: "My order / Talk to someone",
            },
        ]);
    }, 300);
};
site.onAction = (data) => {
    const message = site.messages
        .get(data.conversation)
        .find((m) => m.id === data.message);
    const button = message.parts
        .flatMap((part) => part.buttons ?? [])
        .find((b) => b.id === data.button);
    site.post(
        data.conversation,
        visitor.id,
        [{ type: "text", text: button?.label ?? data.button }],
        { status: "sent" },
    );
    site.stream(data.conversation, bot.id, answers[data.button] ?? ["OK."], {
        parts: [
            {
                type: "text",
                format: "markdown",
                text: (answers[data.button] ?? ["OK."]).join(""),
            },
        ],
    });
};
site.onMessage = (message) => {
    const chunks = ["Thanks, ", "someone will ", "answer you shortly."];
    site.stream(message.conversation, bot.id, chunks, {
        parts: [{ type: "text", text: chunks.join("") }],
    });
};
const visitorClient = new ChatClient(new MemoryTransport(site));
const widget = document.querySelector("chat-widget");
widget.client = visitorClient;
await visitorClient.connect();

// Demo controls, for screenshots and trying it out.
window.demo = {
    server,
    client,
    inbox,
    widget,
    site,
    closeWindow() {
        server.update("conv_wa", {
            capabilities: {
                receipts: true,
                composer: {
                    mode: "templates",
                    reason: "More than 24 hours since Anna's last message: templates only.",
                    templates: [
                        {
                            id: "followup",
                            name: "Follow-up",
                            preview:
                                "Hi {{1}}, can we help with anything else?",
                            params: ["name"],
                        },
                    ],
                },
            },
        });
    },
};
