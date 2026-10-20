# django-chat-ui

A reusable chat interface — WhatsApp, a chatbot, a company's internal
chat, a "contact us" widget — over one protocol. Work in progress.

- [The protocol](docs/protocol.md) (and its [JSON Schema](docs/protocol.schema.json)):
  the contract between the interface and any backend, designed to be
  extended.
- `<chat-thread>`: one conversation, its composer following the
  conversation's capabilities (free text, templates only, buttons only,
  closed). Vanilla JS, no build step, safe under a strict Content Security
  Policy.
- An in-memory transport and fake server, to try it without a backend.

```html
<link rel="stylesheet" href="…/django_chat_ui/chat.css">
<chat-thread conversation="conv_1"></chat-thread>
<script type="module">
  import "…/django_chat_ui/chat-thread.js";
  import { ChatClient } from "…/django_chat_ui/client.js";

  const client = new ChatClient(transport);
  document.querySelector("chat-thread").client = client;
  await client.connect();
</script>
```

Your own kinds of content render with `registerPart("acme.order", render)`;
any other client shows their `fallback` text.

## Demo

```bash
python -m http.server
# open http://localhost:8000/demo/
```

## Development

```bash
npm install
npm test                    # vitest
npx biome check .
```
