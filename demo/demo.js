/**
 * Two conversations on one in-memory server: a chatbot that streams its
 * answers and offers quick replies, and a WhatsApp chat with receipts whose
 * 24-hour window closes. Same <chat-thread>, different capabilities.
 */
import "../src/django_chat_ui/static/django_chat_ui/chat-thread.js";
import { ChatClient } from "../src/django_chat_ui/static/django_chat_ui/client.js";
import { FakeServer, MemoryTransport } from "../src/django_chat_ui/static/django_chat_ui/transports/memory.js";

const me = { id: "p_me", kind: "agent", name: "Rodolfo" };
const bot = { id: "p_bot", kind: "bot", name: "Asistente" };
const ana = { id: "p_ana", kind: "contact", name: "Ana García", handle: "+34 600 000 000" };
const minutesAgo = (n) => new Date(Date.now() - n * 60000).toISOString();

const server = new FakeServer({ me });
server.addConversation(
    {
        id: "conv_bot",
        channel: "bot",
        participants: [me, bot],
        capabilities: { streaming: true, buttons: true, composer: { mode: "free", placeholder: "Pregunta algo…" } },
    },
    [
        { id: "b1", conversation: "conv_bot", author: "p_bot", createdAt: minutesAgo(5), parts: [
            { type: "text", format: "markdown", text: "¡Hola! Soy el **asistente**. ¿En qué te ayudo?" },
            { type: "buttons", buttons: [{ id: "order", label: "Mi pedido" }, { id: "human", label: "Hablar con alguien" }], fallback: "Mi pedido / Hablar con alguien" },
        ] },
    ],
);
server.addConversation(
    {
        id: "conv_wa",
        channel: "whatsapp",
        participants: [me, ana],
        capabilities: { receipts: true, typing: true, attachments: { types: ["image", "file"] }, composer: { mode: "free" } },
    },
    [
        { id: "w1", conversation: "conv_wa", author: "p_ana", createdAt: minutesAgo(30), parts: [{ type: "text", text: "Hola, ¿tenéis la talla M?" }] },
        { id: "w2", conversation: "conv_wa", author: "p_me", createdAt: minutesAgo(28), status: "read", parts: [{ type: "text", text: "¡Sí! Te paso la foto." }] },
        { id: "w3", conversation: "conv_wa", author: "p_me", createdAt: minutesAgo(28), status: "read", parts: [{ type: "image", url: "shirt.svg", alt: "Camiseta azul, talla M", width: 240, height: 150 }] },
        { id: "w4", conversation: "conv_wa", author: "p_ana", createdAt: minutesAgo(27), parts: [{ type: "text", text: "Perfecto, gracias 🙌" }] },
    ],
);

const answers = {
    order: ["Tu pedido ", "**A-1029** ", "sale hoy ", "con MRW."],
    human: ["Te paso ", "con una persona ", "en un momento."],
};

async function botSays(chunks, buttons) {
    await server.stream("conv_bot", "p_bot", chunks, {
        parts: [
            { type: "text", format: "markdown", text: chunks.join("") },
            ...(buttons ? [{ type: "buttons", buttons, fallback: buttons.map((b) => b.label).join(" / ") }] : []),
        ],
    });
}

server.onAction = (data) => {
    // The reply chosen, as the user's message (as WhatsApp shows it).
    const message = server.messages.get(data.conversation).find((m) => m.id === data.message);
    const button = message.parts.flatMap((part) => part.buttons ?? []).find((b) => b.id === data.button);
    server.post(data.conversation, me.id, [{ type: "text", text: button?.label ?? data.button }], { status: "sent" });
    botSays(answers[data.button] ?? ["Vale."]);
};
server.onMessage = (message) => {
    if (message.conversation === "conv_bot") {
        botSays(["Déjame ", "mirarlo… ", "¿Es sobre un pedido?"], [{ id: "order", label: "Sí, un pedido" }]);
    } else {
        // WhatsApp: delivered, then read, then the window closes.
        setTimeout(() => server.emit("message.updated", { id: message.id, conversation: "conv_wa", status: "delivered" }), 600);
        setTimeout(() => server.emit("message.updated", { id: message.id, conversation: "conv_wa", status: "read" }), 1400);
    }
};

const client = new ChatClient(new MemoryTransport(server));
for (const thread of document.querySelectorAll("chat-thread")) thread.client = client;
await client.connect();

// Demo controls, for screenshots and trying it out.
window.demo = {
    server,
    client,
    closeWindow() {
        server.update("conv_wa", {
            capabilities: {
                receipts: true,
                composer: {
                    mode: "templates",
                    reason: "Han pasado más de 24 horas desde el último mensaje de Ana: solo plantillas.",
                    templates: [
                        { id: "followup", name: "Seguimiento", preview: "Hola {{1}}, ¿podemos ayudarte en algo más?", params: ["nombre"] },
                    ],
                },
            },
        });
    },
};
