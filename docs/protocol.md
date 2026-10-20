# Chat UI protocol — version 1.0 (draft)

A small contract between a chat interface and whatever serves its
conversations: WhatsApp, a chatbot, a company's internal chat, a "contact
us" widget, or anything else. The interface only speaks this protocol;
each backend translates its channel to it. The protocol is a **base**:
everything in it is designed to be extended by whoever adopts it, without
forking it and without breaking other clients.

The key words MUST, MUST NOT, SHOULD, SHOULD NOT and MAY are to be
read as in [RFC 2119](https://www.rfc-editor.org/rfc/rfc2119).

## Contents

1. [Concepts](#1-concepts)
2. [Conventions](#2-conventions)
3. [Extensibility](#3-extensibility)
4. [Data types](#4-data-types)
5. [Parts](#5-parts)
6. [Capabilities](#6-capabilities)
7. [Frames, events and commands](#7-frames-events-and-commands)
8. [Session: hello and resume](#8-session-hello-and-resume)
9. [History](#9-history)
10. [Transports](#10-transports)
11. [Security](#11-security)
12. [Extending the protocol](#12-extending-the-protocol)
13. [Examples](#13-examples)

## 1. Concepts

| Term | Meaning |
|---|---|
| **Conversation** | A thread of messages between participants, on one channel. |
| **Participant** | Someone or something taking part: a user, an agent, a bot, an external contact, the system. |
| **Message** | One entry of a conversation, made of **parts**. |
| **Part** | A piece of content: text, an image, buttons, a card… |
| **Channel** | Where a conversation lives (`whatsapp`, `bot`, `internal`, `web`…). The interface doesn't depend on it: it reads the conversation's **capabilities**. |
| **Capabilities** | What a conversation allows (receipts, attachments, streaming…), and what a client can render. |
| **Event** | Server → client: something happened (`message.created`, `typing`…). |
| **Command** | Client → server: do something (`message.send`, `message.read`…). |
| **Transport** | How frames travel (SSE + HTTP, WebSocket, polling). Not part of the data model. |

## 2. Conventions

- Frames are JSON objects, UTF-8.
- Identifiers are opaque **strings** (never numbers): clients MUST NOT
  parse them.
- Timestamps are RFC 3339 strings in UTC: `"2026-10-20T10:00:00Z"`.
- Names of fields are `camelCase`; names of types, events and commands are
  lowercase, dot-separated (`message.created`).
- Optional fields MAY be omitted; omitted and `null` mean the same.
- Text is plain text unless a part says otherwise. **No HTML** anywhere in
  the protocol (see [Security](#11-security)).

## 3. Extensibility

Extensibility follows five rules. They are what lets anyone add things to
the protocol while every other client keeps working.

### 3.1 Must-ignore

A receiver MUST ignore what it doesn't understand, and keep going:

- an unknown **field** on any object;
- an unknown **event** or **command** type (a server answers an unknown
  command with an `error` of code `unknown_command`, see 7.4);
- an unknown **capability**;
- an unknown **part** type: the interface renders its `fallback` (5.1).

So new fields, events, parts and capabilities are never breaking changes.

### 3.2 Namespaces

Names defined by this protocol have **no prefix**: `text`, `image`,
`message.created`, `receipts`. Everything else MUST be namespaced, so two
extensions never collide and none collides with a future version of the
protocol:

```
<namespace>.<name>       e.g.  acme.order   shop.cart.updated   wa.template
```

The namespace is a short, lowercase name owned by whoever defines the
extension (a company, a package: `acme`, `shop`, `wa`). Names of the
protocol with a dot (`message.created`) are not namespaces: they're the
protocol's own, listed in this document. A namespace MUST NOT be one of
the protocol's reserved words: `message`, `conversation`, `participant`,
`typing`, `read`, `presence`, `action`, `hello`, `ready`, `ack`, `error`,
`history`, `chat`.

### 3.3 Extension data: `ext` and `meta`

Every object of the protocol (conversation, participant, message, part,
frame) MAY have two open objects:

- **`ext`** — data defined by an extension, keyed by its namespace. Other
  clients ignore it; clients that know the extension read their key:

  ```json
  "ext": { "acme": { "orderId": "A-1029", "priority": "high" } }
  ```

- **`meta`** — the application's own data, with no meaning in the
  protocol, round-tripped unchanged (an internal id, a CRM reference…).

Neither is ever interpreted by a client that doesn't know it.

### 3.4 Fallbacks

Anything that adds **content** carries a way to show it without knowing
it: every part MAY have a `fallback` text, and an extension part MUST have
one (5.1). An extension that adds **behaviour** (an event, a command, a
capability) MUST be optional: a peer that ignores it still works.

### 3.5 Versions

The protocol has a version `MAJOR.MINOR` (this document: `1.0`).

- **Minor** versions only add optional things (fields, parts, events,
  capabilities): every `1.x` client works with every `1.x` server.
- **Major** versions MAY change or remove things.
- Client and server exchange their versions in the session (section 8);
  each side uses only what both support.

Extensions MAY version themselves too, in their capability (6.3):
`"acme.order": { "version": "2" }`.

## 4. Data types

### 4.1 Participant

```json
{
  "id": "p_7",
  "kind": "contact",
  "name": "Ana García",
  "avatar": "https://example.com/a/7.png",
  "handle": "+34 600 000 000",
  "ext": {},
  "meta": {}
}
```

| Field | Type | |
|---|---|---|
| `id` | string | Required. |
| `kind` | string | Required. `user` (the person using this client), `agent` (staff answering), `bot`, `contact` (someone outside: a WhatsApp number, a visitor), `system`. Extension kinds are namespaced (`acme.supervisor`); unknown kinds render as `contact`. |
| `name` | string | Display name. |
| `avatar` | string (URL) | |
| `handle` | string | How the channel knows them: a phone number, an email, a username. |
| `ext`, `meta` | object | 3.3. |

The client learns which participant it is from `ready.me` (8.2).

### 4.2 Conversation

```json
{
  "id": "conv_1",
  "channel": "whatsapp",
  "title": "Ana García",
  "participants": [ { "id": "p_7", "kind": "contact", "name": "Ana García" } ],
  "capabilities": { "receipts": true, "composer": { "mode": "free" } },
  "unread": 2,
  "lastMessage": { "...": "a Message (4.3), maybe without its parts" },
  "state": "open",
  "updatedAt": "2026-10-20T10:00:00Z",
  "ext": {},
  "meta": {}
}
```

| Field | Type | |
|---|---|---|
| `id` | string | Required. |
| `channel` | string | Informative: the interface MUST NOT change behaviour by channel, only by `capabilities`. Protocol values: `web`, `whatsapp`, `bot`, `internal`, `email`, `sms`, `telegram`; others are namespaced. |
| `title` | string | |
| `participants` | Participant[] | |
| `capabilities` | object | Section 6. |
| `unread` | integer | Messages this client hasn't read. |
| `lastMessage` | Message | For lists. |
| `state` | string | `open`, `pending` (waiting for someone), `closed`. Extension states are namespaced. |
| `updatedAt` | timestamp | |
| `ext`, `meta` | object | 3.3. |

### 4.3 Message

```json
{
  "id": "m_123",
  "clientId": "c_9f2",
  "conversation": "conv_1",
  "author": "p_7",
  "parts": [ { "type": "text", "text": "Hola" } ],
  "status": "delivered",
  "replyTo": "m_100",
  "createdAt": "2026-10-20T10:00:00Z",
  "editedAt": null,
  "deleted": false,
  "streaming": false,
  "reactions": [ { "emoji": "👍", "by": ["p_1"] } ],
  "ext": {},
  "meta": {}
}
```

| Field | Type | |
|---|---|---|
| `id` | string | Required, given by the server. |
| `clientId` | string | The id the client gave it when sending (7.3): how a client matches its optimistic message with the server's. |
| `conversation` | string | Required. |
| `author` | string | Participant id. Required, except for `system` messages, which MAY omit it. |
| `parts` | Part[] | Required, at least one (an empty `text` for a deleted message is fine). |
| `status` | string | Only meaningful for the client's own messages: `sending` (client-side only), `sent`, `delivered`, `read`, `failed`. |
| `error` | Error | When `status` is `failed` (7.4). |
| `replyTo` | string | Id of the message it answers. |
| `createdAt` | timestamp | Required. |
| `editedAt` | timestamp | |
| `deleted` | boolean | Deleted messages keep their place; their parts MAY be emptied. |
| `streaming` | boolean | `true` while a bot is still writing it (7.2, `message.delta`). |
| `reactions` | array | With the `reactions` capability. |
| `ext`, `meta` | object | 3.3. |

### 4.4 Error

```json
{ "code": "window_closed", "message": "Only templates can be sent now.", "retry": false }
```

`code` is machine-readable (protocol codes below; extension codes
namespaced), `message` is for people, `retry` says whether retrying the
same command can work.

Protocol codes: `bad_request`, `unauthorized`, `forbidden`, `not_found`,
`unknown_command`, `unsupported` (a capability the conversation lacks),
`window_closed`, `too_large`, `rate_limited`, `channel_error`, `internal`.

## 5. Parts

### 5.1 Common fields

Every part has:

| Field | Type | |
|---|---|---|
| `type` | string | Required. A protocol type (5.2) or a namespaced one. |
| `fallback` | string | Plain text shown by a client that can't render the part. **Required for extension types**; optional, but recommended, for protocol types other than `text`. |
| `ext`, `meta` | object | 3.3. |

Rendering rule: a client renders a part of a type it knows; otherwise its
`fallback`; otherwise a generic "unsupported content" line. A part is never
silently dropped.

### 5.2 Protocol parts

| `type` | Fields | |
|---|---|---|
| `text` | `text` (string, required), `format` (`plain` default, or `markdown`) | `markdown` is a safe subset: emphasis, links, lists, code; never raw HTML. |
| `image` | `url` (required), `alt`, `width`, `height`, `thumbnail` | |
| `video` | `url` (required), `poster`, `duration` (seconds), `mime` | |
| `audio` | `url` (required), `duration`, `mime`, `voice` (boolean: a voice note) | |
| `file` | `url` (required), `name`, `size` (bytes), `mime` | |
| `location` | `lat`, `lng` (required), `name`, `address` | |
| `contact` | `name` (required), `phones` (string[]), `emails` (string[]) | A shared contact card. |
| `buttons` | `buttons`: `{ id, label, style? }[]` (required), `persist` (boolean) | Quick replies: clicking sends an `action` command (7.3). Without `persist`, they hide once one is used or another message comes. `style`: `primary`, `secondary`, `danger`. |
| `link` | `url` (required), `title`, `description`, `image` | A link preview. |
| `card` | `title`, `text`, `image`, `buttons` (as above), `url` | Rich card, as bots send. |
| `system` | `text` (required), `code` | An event in the thread ("Ana joined", "Assigned to support"). `code` is machine-readable. |
| `template` | `template` (id, required), `params` (object) | A pre-approved message, for `composer.mode: "templates"` (6.1, 13.2). Its `fallback` is the rendered text. |

Attachments that are being uploaded MAY carry `progress` (0–1) client-side.

### 5.3 Extension parts

```json
{
  "type": "acme.order",
  "fallback": "Order A-1029: 2 items, 59.90 €",
  "ext": { "acme": { "orderId": "A-1029", "total": "59.90", "currency": "EUR" } }
}
```

The fields of an extension part SHOULD go under `ext.<namespace>`: so a
future protocol field never clashes with them. See section 12.

## 6. Capabilities

Two sets, both open to extension.

### 6.1 Conversation capabilities

Sent by the server with each conversation (`conversation.capabilities`),
and updated with `conversation.updated` (a WhatsApp window closing changes
them). The interface adapts to them; it never checks `channel`.

```json
{
  "attachments": { "types": ["image", "video", "audio", "file"], "maxSize": 16777216 },
  "receipts": true,
  "typing": true,
  "presence": false,
  "streaming": false,
  "buttons": true,
  "replies": true,
  "reactions": true,
  "edit": false,
  "delete": false,
  "history": true,
  "composer": {
    "mode": "free",
    "maxLength": 4096,
    "placeholder": "Write a message…"
  }
}
```

| Capability | Type | Meaning when on |
|---|---|---|
| `attachments` | `false` or `{ types, maxSize }` | The client may send those part types. |
| `receipts` | boolean | Messages report `delivered` / `read`. |
| `typing` | boolean | `typing` events are sent and accepted. |
| `presence` | boolean | `presence` events about participants. |
| `streaming` | boolean | Messages may arrive with `streaming` and `message.delta`. |
| `buttons` | boolean | `buttons` and `card` parts, and the `action` command. |
| `replies` | boolean | `replyTo` on sent messages. |
| `reactions` | boolean | `message.react`. |
| `edit` / `delete` | boolean | `message.edit` / `message.delete` on own messages. |
| `history` | boolean | Older messages can be fetched (section 9). |
| `composer` | object | What the user may write: |
| `composer.mode` | string | `free` (anything), `templates` (only templates: WhatsApp outside its 24-hour window), `actions` (only buttons: a bot's menu), `closed` (nothing; `composer.reason` says why). Extension modes are namespaced; unknown modes behave as `closed`. |
| `composer.templates` | `{ id, name, preview, params? }[]` | With `templates`: what can be sent (`message.send` with a `template` part, 13.2). |
| `composer.maxLength` | integer | |
| `composer.placeholder`, `composer.reason` | string | Texts for the interface. |

Missing capabilities are **off**, except `composer.mode`, which defaults to
`free`.

### 6.2 Client capabilities

Sent by the client in `hello` (8.1): what it can render and handle.

```json
{
  "parts": ["text", "image", "video", "audio", "file", "buttons", "card", "acme.order"],
  "streaming": true,
  "formats": ["plain", "markdown"]
}
```

A server SHOULD use them to degrade what it sends: a `card` as text and
links for a client without it, a `markdown` text as `plain`. It MUST NOT
assume a client renders a part type it didn't list.

### 6.3 Extension capabilities

Namespaced keys, in either set, with an object value (so they can grow):

```json
"acme.order": { "version": "2", "editable": true }
```

## 7. Frames, events and commands

### 7.1 Frame

Everything that travels is a frame:

```json
{
  "type": "message.updated",
  "id": "f_881",
  "seq": 1042,
  "ref": "cmd_17",
  "data": { "id": "m_123", "conversation": "conv_1", "status": "read" },
  "ext": {}
}
```

| Field | | |
|---|---|---|
| `type` | Required. | The event or command. |
| `id` | Commands: required. Events: optional. | Unique per sender; what `ref` and `ack` point to. |
| `seq` | Events | Increasing number of the event in this client's stream, used to resume (8.3). |
| `ref` | Events | The command this event answers, if any. |
| `data` | Required (MAY be `{}`). | The payload, below. |
| `ext` | | 3.3. |

### 7.2 Events (server → client)

| `type` | `data` | |
|---|---|---|
| `ready` | `{ protocol, me, capabilities, conversations? }` | Answer to `hello` (8.2). |
| `ack` | `{ }` | A command was accepted (`ref` is its id). |
| `error` | Error, plus `{ fatal? }` | A command failed (`ref`), or the session did (`fatal: true`). |
| `conversation.created` | Conversation | |
| `conversation.updated` | Partial conversation: `id` and the fields that changed | E.g. new capabilities, a new title, `state: "closed"`. |
| `conversation.removed` | `{ id }` | The client no longer has access to it. |
| `message.created` | Message | A new message, the client's own included (matched by `clientId`). |
| `message.updated` | Partial message: `id`, `conversation` and what changed | Status, edit, deletion, reactions, end of streaming. |
| `message.delta` | `{ id, conversation, part, text }` | Streaming: append `text` to part number `part` (0-based) of message `id`. A delta for a part that doesn't exist yet creates it as `text`. |
| `typing` | `{ conversation, participant, active }` | |
| `read` | `{ conversation, participant, until }` | `participant` has read everything up to message `until`. |
| `presence` | `{ participant, status, lastSeen? }` | `status`: `online`, `away`, `offline`. |
| `history` | `{ conversation, messages, before?, more }` | Answer to `history.fetch` (section 9). |

A streamed message: `message.created` with `streaming: true` (its parts
MAY be empty or partial), then any number of `message.delta`, then
`message.updated` with `streaming: false` and, optionally, the final
`parts` (which replace the accumulated ones).

### 7.3 Commands (client → server)

Every command has an `id`; the server answers with `ack` or `error`
referring to it, besides any events it causes.

| `type` | `data` | Needs |
|---|---|---|
| `hello` | `{ protocol, client, capabilities, resume? }` | Section 8. |
| `conversation.open` | `{ conversation, limit? }` or `{ with, channel? }` | Subscribe to one, or start one with participants `with`. The server sends its `conversation.created` and a `history` event with its latest messages (section 9), whether or not the conversation has the `history` capability. |
| `conversation.close` | `{ conversation }` | Unsubscribe. |
| `message.send` | `{ conversation, clientId, parts, replyTo? }` | `composer.mode` allows it. **Idempotent by `clientId`**: resending the same `clientId` MUST NOT create a second message. |
| `message.edit` | `{ id, parts }` | `edit` |
| `message.delete` | `{ id }` | `delete` |
| `message.react` | `{ id, emoji, active }` | `reactions` |
| `message.read` | `{ conversation, until }` | |
| `typing` | `{ conversation, active }` | `typing` |
| `action` | `{ conversation, message, button }` | `buttons`: a button or quick reply was used. The server answers with whatever it does (a bot's reply, for instance). |
| `history.fetch` | `{ conversation, before?, limit? }` | `history` (to fetch older messages) |

A client MUST NOT send a command that the conversation's capabilities don't
allow; a server MUST reject it (`unsupported`).

### 7.4 Acknowledgements and errors

- A server MUST answer every command with exactly one `ack` or `error`
  whose `ref` is the command's `id`.
- `message.send` fails as `error` (`ref`), and later failures of a sent
  message (the channel rejected it) come as `message.updated` with
  `status: "failed"` and `error`.
- A client SHOULD retry a command after a transport failure, with the same
  `id` (and, for `message.send`, the same `clientId`): commands are safe to
  repeat.

## 8. Session: hello and resume

### 8.1 hello

The first thing a client sends:

```json
{
  "type": "hello",
  "id": "cmd_1",
  "data": {
    "protocol": ["1.0"],
    "client": { "name": "django-chat-ui", "version": "0.1.0" },
    "capabilities": { "parts": ["text", "image", "buttons"], "streaming": true },
    "resume": { "seq": 1041 }
  }
}
```

`protocol` lists the versions the client speaks.

### 8.2 ready

```json
{
  "type": "ready",
  "ref": "cmd_1",
  "data": {
    "protocol": "1.0",
    "me": { "id": "p_1", "kind": "agent", "name": "Rodolfo" },
    "capabilities": { "acme.order": { "version": "2" } },
    "conversations": [ ],
    "resumed": true
  }
}
```

`protocol` is the version chosen (the highest both speak). Session-level
`capabilities` are those that apply to every conversation (extensions,
mostly). `conversations` MAY list the client's conversations, for an inbox.

### 8.3 Resume

Events carry `seq`. A client that reconnects sends the last `seq` it
handled in `hello.resume`; the server replays what came after, and answers
`resumed: true`. If it can't (too old), it answers `resumed: false`, and
the client reloads what it shows (conversations, then their latest
history).

## 9. History

Opening a conversation (`conversation.open`) brings its latest messages.
With the `history` capability, a client can then fetch older ones, page
by page:

```json
{ "type": "history.fetch", "id": "cmd_8",
  "data": { "conversation": "conv_1", "before": "m_100", "limit": 30 } }
```

```json
{ "type": "history", "ref": "cmd_8",
  "data": { "conversation": "conv_1", "messages": [ ], "before": "m_70", "more": true } }
```

`messages` come oldest first. `before` in the answer is the cursor for the
next page; `more: false` means there's nothing older. Cursors are opaque.

## 10. Transports

The protocol is the same over any transport. Three are defined:

### 10.1 SSE + HTTP (default)

- **Events:** `GET <base>/events` — a
  [Server-Sent Events](https://html.spec.whatwg.org/multipage/server-sent-events.html)
  stream: each frame is one SSE message, `event: <type>`, `id: <seq>`,
  `data: <frame JSON>`. Reconnection uses the browser's `Last-Event-ID`,
  which works as `hello.resume`.
- **Commands:** `POST <base>/commands` with one frame (or an array of
  frames) as JSON. The response body MAY carry the `ack`/`error` frames
  directly; they are also sent on the stream.
- `hello` is the first command; until `ready`, the stream sends only
  `ready` and `error`.

It needs no WebSocket server, and works under a strict Content Security
Policy (`connect-src 'self'`).

### 10.2 WebSocket

One frame per WebSocket text message, both directions, on `<base>/ws`.
The first client frame is `hello`.

### 10.3 Polling

`POST <base>/commands` as above, and `GET <base>/events?after=<seq>`
returning a JSON array of frames. For environments without long-lived
connections.

## 11. Security

- **Authentication** belongs to the transport (the site's session and its
  CSRF token on `POST`, a bearer token…), never to frames.
- **The server decides the author.** It MUST ignore any author a client
  claims, and use the authenticated participant.
- **No HTML.** Clients MUST render text as text, and `markdown` through a
  renderer that drops raw HTML. Extension parts too: a client renders
  their fields as text or through its own templates, never as HTML from
  the payload.
- **URLs:** clients SHOULD only follow `https:` (and same-origin) URLs from
  parts, and open links with `rel="noopener noreferrer"`.
- **Authorization** per conversation: a server MUST only send events of
  conversations the participant may see, and check every command.
- Attachments SHOULD be served from URLs that check access, or expire.

## 12. Extending the protocol

What an adopter can add, and how, without touching this document:

| To add | Do | Others see |
|---|---|---|
| Data on existing objects | `ext.<ns>` (3.3), or `meta` for app-only data | Nothing changes. |
| A kind of content | A part `<ns>.<name>` with a `fallback` (5.3) | Its fallback text. |
| Something that happens | An event `<ns>.<name>` | Nothing (ignored). |
| Something a user does | A command `<ns>.<name>`, gated by a capability | It's never offered to them. |
| A feature of some conversations | A capability `<ns>.<name>: { … }` (6.3) | Off. |
| A kind of participant / state / composer mode | A namespaced value | `contact` / as unknown / `closed`. |
| A transport | Any binding that carries the same frames | Unchanged protocol. |

Guidelines:

1. **Choose one namespace** and use it for everything you add.
2. **Gate behaviour behind a capability**, so a client only offers it
   where the server supports it, and a server knows which clients can take
   it (client capabilities, 6.2).
3. **Always give a fallback** to content.
4. **Version your extension** in its capability, and follow the same
   rules: add optional things, never change their meaning.
5. **Promote** an extension that many adopt: a later minor version of the
   protocol MAY adopt it without the prefix, and servers can send both
   during the transition.

## 13. Examples

### 13.1 A chatbot answering in streaming, with quick replies

```json
{"type": "message.send", "id": "cmd_4", "data": {"conversation": "conv_bot", "clientId": "c_1", "parts": [{"type": "text", "text": "¿Dónde está mi pedido?"}]}}
{"type": "ack", "ref": "cmd_4", "seq": 10, "data": {}}
{"type": "message.created", "seq": 11, "data": {"id": "m_1", "clientId": "c_1", "conversation": "conv_bot", "author": "p_me", "parts": [{"type": "text", "text": "¿Dónde está mi pedido?"}], "status": "sent", "createdAt": "2026-10-20T10:00:00Z"}}
{"type": "message.created", "seq": 12, "data": {"id": "m_2", "conversation": "conv_bot", "author": "p_bot", "parts": [], "streaming": true, "createdAt": "2026-10-20T10:00:01Z"}}
{"type": "message.delta", "seq": 13, "data": {"id": "m_2", "conversation": "conv_bot", "part": 0, "text": "Tu pedido A-1029 "}}
{"type": "message.delta", "seq": 14, "data": {"id": "m_2", "conversation": "conv_bot", "part": 0, "text": "sale hoy."}}
{"type": "message.updated", "seq": 15, "data": {"id": "m_2", "conversation": "conv_bot", "streaming": false, "parts": [
  {"type": "text", "text": "Tu pedido A-1029 sale hoy."},
  {"type": "buttons", "buttons": [{"id": "track", "label": "Seguirlo"}, {"id": "human", "label": "Hablar con alguien"}], "fallback": "Responde: Seguirlo / Hablar con alguien"}
]}}
{"type": "action", "id": "cmd_5", "data": {"conversation": "conv_bot", "message": "m_2", "button": "human"}}
```

### 13.2 WhatsApp: the 24-hour window closes

```json
{"type": "conversation.updated", "seq": 90, "data": {"id": "conv_wa", "capabilities": {"receipts": true, "composer": {
  "mode": "templates",
  "reason": "More than 24 hours since the customer's last message.",
  "templates": [{"id": "followup_es", "name": "Seguimiento", "preview": "Hola {{1}}, ¿podemos ayudarte en algo más?", "params": ["name"]}]
}}}}
{"type": "message.send", "id": "cmd_9", "data": {"conversation": "conv_wa", "clientId": "c_7", "parts": [
  {"type": "template", "template": "followup_es", "params": {"name": "Ana"}, "fallback": "Hola Ana, ¿podemos ayudarte en algo más?"}
]}}
```

Its message uses the `template` part (5.2) with one of the
conversation's `composer.templates`.

### 13.3 Internal chat with an extension part

```json
{"type": "message.created", "seq": 300, "data": {"id": "m_9", "conversation": "conv_team", "author": "p_5", "createdAt": "2026-10-20T12:00:00Z", "parts": [
  {"type": "text", "text": "Este pedido está retrasado:"},
  {"type": "acme.order", "fallback": "Pedido A-1029 · 2 artículos · 59,90 €", "ext": {"acme": {"orderId": "A-1029", "total": "59.90", "currency": "EUR"}}}
]}}
```

A client that registered `acme.order` renders the order card; any other
shows "Pedido A-1029 · 2 artículos · 59,90 €".

### 13.4 A "contact us" widget, before anyone answers

```json
{"type": "conversation.created", "seq": 1, "data": {"id": "conv_v1", "channel": "web", "state": "pending",
  "participants": [{"id": "p_v", "kind": "user", "name": "Visitante"}],
  "capabilities": {"attachments": {"types": ["image", "file"], "maxSize": 5242880}, "typing": true, "composer": {"mode": "free"}}}}
{"type": "message.created", "seq": 2, "data": {"id": "m_s1", "conversation": "conv_v1", "createdAt": "2026-10-20T09:00:00Z", "parts": [
  {"type": "system", "code": "queued", "text": "Te respondemos en unos minutos."}
]}}
```
