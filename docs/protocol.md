# django-chat-ui on Matrix — profile 1.0

django-chat-ui speaks [Matrix](https://spec.matrix.org/v1.11/client-server-api/):
its web components are Matrix clients, and its Django app is a Matrix
homeserver (without federation nor end-to-end encryption). A Matrix client
or bot — the tests run [matrix-js-sdk](https://github.com/matrix-org/matrix-js-sdk)
against it — can use a site that has it, and the components can use other
homeservers.

What a business chat needs and Matrix doesn't have (quick replies, cards,
WhatsApp's templates and 24-hour window, AI answers written as they come,
what each conversation allows) are **extensions**, in Matrix's own way:
namespaced under `io.github.rodolvbg.chat`, always with a fallback that any
other client shows. A site adds its own the same way (section 9).

The key words MUST, MUST NOT, SHOULD and MAY are to be read as in
[RFC 2119](https://www.rfc-editor.org/rfc/rfc2119).

## Contents

1. [Concepts](#1-concepts)
2. [Identifiers and sessions](#2-identifiers-and-sessions)
3. [The API served](#3-the-api-served)
4. [Room state](#4-room-state)
5. [Messages](#5-messages)
6. [Ephemeral events](#6-ephemeral-events)
7. [AI answers, as they're written](#7-ai-answers-as-theyre-written)
8. [What clients may send](#8-what-clients-may-send)
9. [Extending it](#9-extending-it)
10. [WhatsApp, and other channels](#10-whatsapp-and-other-channels)
11. [Examples](#11-examples)

## 1. Concepts

| django-chat-ui | Matrix |
|---|---|
| Conversation | A room (`!7:example.com`). |
| Participant (user, agent, bot, contact, system) | A user (`@p3:example.com`), with this package's block in its `m.room.member` (section 4.2). |
| Message | An `m.room.message` event. |
| Its kinds of content (text, image, buttons, card…) | Its `msgtype`, and this package's blocks (section 5). |
| Reactions, edits, replies, deletions | `m.annotation`, `m.replace`, `m.in_reply_to`, redactions. |
| Read, delivered | Receipts: `m.read`, and this package's `delivered`. |
| Typing | `m.typing`. |
| What a conversation allows | This package's `capabilities` state event (section 4.3). |
| Its channel (WhatsApp, a bot, internal, the web) and state (open, pending, closed) | This package's `conversation` state event (section 4.1). |
| A message being written (an AI's) | This package's ephemeral `stream` event (section 7). |
| History, resuming after a disconnection | `/sync` tokens, `/messages`. |

## 2. Identifiers and sessions

The server's name is `CHAT_UI["SERVER_NAME"]` (default `localhost`):

| | Format | Example |
|---|---|---|
| User ID | `@p<participant pk>:<server>` | `@p3:shop.example` |
| Room ID | `!<conversation pk>:<server>` | `!7:shop.example` |
| Event ID | `$<pk>` | `$1042` |
| Media | `mxc://<server>/<media id>` | `mxc://shop.example/k2J…` |
| The server's own sender (system notices) | `@system:<server>` | |
| `next_batch` of `/sync` | `s<position>` | `s1300` |
| `prev_batch`, tokens of `/messages` | `t<event pk>` | `t1001` |

Clients MUST treat them as opaque.

A client authenticates in either way:

- **An access token**, from `POST /login` with `m.login.password` (a user
  of the site and their password; their Matrix ID works as their user too),
  sent as `Authorization: Bearer …`. Any Matrix client does this.
- **The site's session**, for this package's components on the same site
  (and the visitors of a "contact us" widget, who aren't logged in, when the
  backend allows them). Unsafe methods then need the site's CSRF token
  (`X-CSRFToken`). Cookies aren't sent cross-origin: the CORS headers are
  `Access-Control-Allow-Origin: *`, for clients with a token.

## 3. The API served

Under the base URL where the app's URLs are included (`/chat` in the
examples: any Matrix client can use `https://<site>/chat` as its
homeserver). `GET /_matrix/client/versions` lists `v1.1`–`v1.11`, and
`io.github.rodolvbg.chat` in `unstable_features`.

| Endpoint | |
|---|---|
| `GET/POST /login`, `POST /logout`, `POST /logout/all`, `GET /account/whoami` | Sessions (section 2). |
| `GET /sync` | `since`, `timeout` (long polling: up to `SYNC_TIMEOUT` seconds; under ASGI it holds no thread), `filter` (only `room.timeline.limit`, inline or uploaded), `full_state`. |
| `POST /user/{userId}/filter`, `GET …/filter/{filterId}` | |
| `GET/PUT /user/{userId}/account_data/{type}`, `…/rooms/{roomId}/account_data/{type}` | |
| `GET /joined_rooms`, `POST /createRoom` | Section 8.4. |
| `PUT /rooms/{roomId}/send/{eventType}/{txnId}` | Idempotent by `txnId`. Section 8. |
| `PUT /rooms/{roomId}/redact/{eventId}/{txnId}` | Section 8.3. |
| `GET /rooms/{roomId}/messages` | `from`, `dir` (`b`, `f`), `limit`. |
| `GET /rooms/{roomId}/event/{eventId}`, `…/state`, `…/state/{type}/{key}`, `…/members`, `…/joined_members` | Changing the state is the server's (`M_FORBIDDEN`). |
| `PUT /rooms/{roomId}/typing/{userId}` | Accepted and ignored where the conversation doesn't show it. |
| `POST /rooms/{roomId}/receipt/{type}/{eventId}`, `…/read_markers` | `m.read`, `m.read.private`, `m.fully_read`. |
| `POST /rooms/{roomId}/leave` | |
| `GET /profile/{userId}[/{field}]` | Of whoever shares a room with the requester. |
| `GET /capabilities`, `GET /pushrules/` | What clients ask for at start (no push). |
| `POST /_matrix/media/v3/upload`, `GET /_matrix/client/v1/media/download/…` (and `/_matrix/media/v3/download/…`, thumbnails), `…/media/config` | A file is downloaded by its uploader, and by the participants of the conversation a message sent it to. What isn't an image, video or audio is served as a download. |

Anything else under `/_matrix/` answers `404 M_UNRECOGNIZED`. Not
implemented: federation, end-to-end encryption, registration, guests,
presence, push, threads, spaces, VoIP, invites (participants join directly:
the server decides who takes part).

`/sync` follows the specification. A client away for longer than the log is
kept (`chat_ui_prune`) gets every room again, its timelines `limited`.

## 4. Room state

The standard events (`m.room.create`, `m.room.member`, `m.room.name`,
`m.room.power_levels`, `m.room.join_rules`, `m.room.history_visibility`) and
two of this package's, all with `state_key: ""` unless said. Only the server
changes the state (`state_default: 100`).

### 4.1 `io.github.rodolvbg.chat.conversation`

```json
{ "channel": "whatsapp", "state": "pending", "ext": { "com.acme": { "priority": "high" } } }
```

| Field | |
|---|---|
| `channel` | Informative: `web`, `whatsapp`, `bot`, `internal`, `email`, `sms`, `telegram`, or a namespaced one. A client MUST NOT change behaviour by channel, only by capabilities. |
| `state` | `open`, `pending` (waiting for someone), `closed`, or a namespaced one. Nothing can be sent to a closed conversation. |
| `ext` | A site's data, keyed by its namespace (section 9). |

### 4.2 Participants: `m.room.member`

Its content has, besides `membership` and `displayname`:

```json
"io.github.rodolvbg.chat.participant": {
  "kind": "contact", "handle": "+1 555 0100", "avatar": "https://…", "ext": {}
}
```

`kind`: `user` (the person using the client), `agent` (staff answering),
`bot`, `contact` (someone outside: a WhatsApp number, a visitor), `system`,
or a namespaced one (shown as `contact`). `handle`: how the channel knows
them. `avatar`: an `https:` URL (`avatar_url` is for `mxc://` ones).

### 4.3 `io.github.rodolvbg.chat.capabilities`

What a conversation allows. Missing ones are **off**, except
`composer.mode`, which defaults to `free`. The server enforces them
(section 8); clients offer only what they allow.

```json
{
  "attachments": { "types": ["image", "video", "audio", "file"], "maxSize": 16777216 },
  "receipts": true,
  "typing": true,
  "buttons": true,
  "replies": true,
  "reactions": { "emojis": ["👍", "✅"] },
  "edit": false,
  "delete": false,
  "history": true,
  "composer": { "mode": "free", "maxLength": 4096, "placeholder": "Write a message…" }
}
```

| Capability | Type | When on |
|---|---|---|
| `attachments` | `false` or `{ types, maxSize }` | Files of those kinds can be sent. |
| `receipts` | boolean | Statuses (sent, delivered, read) are shown. |
| `typing` | boolean | `m.typing` is sent and shown. |
| `buttons` | boolean | Quick replies and cards' buttons can be used (section 5.3). |
| `replies` | boolean | `m.in_reply_to`. |
| `reactions` | `false`, `true` or `{ emojis }` | `m.reaction`: any emoji, or only those. |
| `edit` / `delete` | boolean | `m.replace` / redactions of one's own messages. |
| `history` | boolean | Older messages are offered (`/messages`). |
| `composer.mode` | string | `free` (anything), `templates` (only templates: WhatsApp outside its 24-hour window), `actions` (only buttons: a bot's menu), `closed` (nothing; `composer.reason` says why), or a namespaced one (treated as `closed`). |
| `composer.templates` | `{ id, name, preview, params }[]` | With `templates`: what can be sent (section 5.4). `preview` has `{{1}}`, `{{2}}`… (or `{{name}}`) for `params`. |
| `composer.maxLength`, `placeholder`, `reason` | | For the composer. |

Extensions add namespaced capabilities, with an object value (so they can
grow): `"com.acme.orders": { "version": "2" }`.

## 5. Messages

### 5.1 Matrix's message types

`m.text`, `m.notice` (a bot's), `m.emote`, `m.image`, `m.video`, `m.audio`
(with `org.matrix.msc3245.voice` for a voice note), `m.file` and
`m.location`, as the specification has them. HTML (`format:
"org.matrix.custom.html"`, `formatted_body`) is rendered from the
specification's safe subset, rebuilt node by node: never inserted as it
comes. The server writes it for markdown (`content.text(…, markdown=True)`),
with its plain text as `body`.

### 5.2 Fallbacks

Everything this package (or a site) adds is shown by any other client
through what Matrix already has: a block's message keeps a `body` (and
`formatted_body`) that says it in words, and a message type of its own
always has a `body`. A client that doesn't know a block ignores it; one
that doesn't know a message type shows its `body`, as the specification
asks. Nothing is silently dropped.

### 5.3 Quick replies: the `buttons` block, and answers

Under a message (an `m.text`, `m.notice` or a card):

```json
{
  "msgtype": "m.text",
  "body": "How can I help?\n\n• My order\n• Talk to someone",
  "io.github.rodolvbg.chat.buttons": {
    "body": "How can I help?",
    "buttons": [ { "id": "order", "label": "My order" }, { "id": "human", "label": "Talk to someone", "style": "primary" } ],
    "persist": false
  }
}
```

The block repeats the text before the buttons (`body`, `formatted_body`):
the message's own have the labels too, for other clients. `style`:
`primary`, `secondary` (default), `danger`. Without `persist`, they're done
once one is used or another message comes.

Using one is sending its answer — its label, as WhatsApp writes it — with
the `action` block, as a reply to the message:

```json
{
  "msgtype": "m.text",
  "body": "My order",
  "io.github.rodolvbg.chat.action": { "event_id": "$41", "button": "order" },
  "m.relates_to": { "m.in_reply_to": { "event_id": "$41" } }
}
```

The server checks the button and writes the label itself. A client without
buttons answers by writing (the backend may match the text).

### 5.4 This package's message types and blocks

| | Content | Others see |
|---|---|---|
| `msgtype: io.github.rodolvbg.chat.card` | `"io.github.rodolvbg.chat.card": { title, text, image, url }`, and a `buttons` block | Its `body`: title, text, link, the buttons' labels. |
| `msgtype: io.github.rodolvbg.chat.template` | `"io.github.rodolvbg.chat.template": { id, params }` | Its `body`: the template's text, filled in (by the server). |
| `msgtype: io.github.rodolvbg.chat.contact` | `"io.github.rodolvbg.chat.contact": { name, phones, emails }` | Its `body`: name, phones, emails. |
| The `link` block (on an `m.text`; on an `m.location`, its `title` and `description` name the place) | `{ url, title, description, image }` | The text: title and URL. |
| The `system` block (on an `m.notice` from `@system:…`) | `{ code? }`: "Ana joined", "Assigned to support" | A notice. |

### 5.5 Relations

Replies (`m.in_reply_to`), edits (`m.replace`, with `m.new_content`; only of
one's own messages), reactions (`m.reaction`, `m.annotation`; one per emoji
and person, else `M_DUPLICATE_ANNOTATION`; taken back by redacting it) and
deletions (`m.room.redaction`) are Matrix's, gated by the capabilities.

## 6. Ephemeral events

In a room's `ephemeral` of `/sync`:

| Type | Content | |
|---|---|---|
| `m.typing` | `{ user_ids }` | |
| `m.receipt` | `{ <event id>: { <type>: { <user id>: { ts } } } }` | `m.read`, and `io.github.rodolvbg.chat.delivered`: the channel delivered it (the server's, from an integration). A message is *read* when anyone else's `m.read` is at or after it, *delivered* when their `delivered` is. |
| `io.github.rodolvbg.chat.stream` | `{ id, sender, body, markdown? }` or `{ id, sender, done: true }` | A message being written: section 7. |
| `io.github.rodolvbg.chat.status` | `{ event_id, status, error? }` | What receipts don't say: `failed` (the channel rejected it), with an `error` (`{ errcode, error }`). Also in the message's `unsigned`, under the same key. |

Extensions send their own (`services.ephemeral()`); clients ignore what they
don't know.

## 7. AI answers, as they're written

While an AI model writes, the server sends the text so far as `stream`
ephemeral events (every 0.1 s or 200 characters), and its author as
`m.typing`. When it ends, it sends the message, with the stream's `id`:

```json
{ "type": "io.github.rodolvbg.chat.stream", "content": { "id": "9f2c", "sender": "@p5:shop.example", "body": "Your order **A-1029** ships", "markdown": true } }
{ "type": "m.room.message", "content": { "msgtype": "m.text", "body": "Your order A-1029 ships today.", "format": "org.matrix.custom.html", "formatted_body": "<p>Your order <strong>A-1029</strong> ships today.</p>", "io.github.rodolvbg.chat.stream": { "id": "9f2c" } } }
```

This package's clients show the message growing, and replace it with the
real one. Any other sees the bot typing, then its message: one event, not
an edit per word (unlike [MSC4357](https://github.com/matrix-org/matrix-spec-proposals/pull/4357)'s
live messages). If the model fails, what came is sent; if nothing came,
`{ id, done: true }` ends it.

An agent of any framework that speaks [AG-UI](https://docs.ag-ui.com)
(LangGraph, CrewAI, Mastra, Pydantic AI…) answers this way through
`django_chat_ui.agui.AgUiAgent`: its `TEXT_MESSAGE_*` events become the
stream, and the conversation its `RunAgentInput`.

## 8. What clients may send

### 8.1 Messages

- Nothing to a `closed` conversation (`M_FORBIDDEN`).
- `composer.mode`: `free` takes texts (`m.text`, `m.emote`, with HTML),
  files and templates; `templates`, only templates
  (`IO.GITHUB.RODOLVBG.CHAT.WINDOW_CLOSED`); `actions`, only buttons' answers;
  anything else, nothing (`IO.GITHUB.RODOLVBG.CHAT.UNSUPPORTED`, with
  `composer.reason`).
- Texts: not empty, at most `composer.maxLength` (`M_TOO_LARGE`).
- Files: uploaded by the sender, of a kind in `attachments.types` and at
  most `maxSize`. Their `info` is rebuilt by the server.
- Templates: one of `composer.templates`; the server writes their text.
- A site's message types (a namespaced `msgtype` with a `body`), when its
  backend allows them (`validate_content`). This package's blocks are the
  server's to send: a client's are left out (so nobody fakes a system
  notice or a button).
- `m.notice` is a bot's: not for clients.

### 8.2 Reactions, edits, replies

As section 5.5, where the capabilities allow them.

### 8.3 Redactions

One's own messages (with `delete`), reactions and events of a site's types.
Never state events.

### 8.4 Starting a conversation

`POST /createRoom` with `invite` (user IDs): the backend decides who may
start one with whom (`can_start`). Without `invite` — the "contact us"
widget — it goes to the support team, `pending`. Its channel, in
`initial_state`:

```json
{ "invite": [], "initial_state": [ { "type": "io.github.rodolvbg.chat.conversation", "state_key": "", "content": { "channel": "web" } } ] }
```

### 8.5 Errors

Matrix's (`{ "errcode", "error" }`, its HTTP statuses), and this package's:
`IO.GITHUB.RODOLVBG.CHAT.UNSUPPORTED` (403: the conversation doesn't allow
it) and `IO.GITHUB.RODOLVBG.CHAT.WINDOW_CLOSED` (403: only templates now).

## 9. Extending it

A site, or a package on top of this one, adds what it needs the way this
package does: under **its own namespace** (reverse DNS of a domain it
controls: `com.acme`), never `m.` nor `io.github.rodolvbg.chat`.

| To add | Do | Others see |
|---|---|---|
| Data on a conversation or a participant | `ext` (`serialize_conversation`, `serialize_participant`), keyed by your namespace | Nothing changes. |
| A kind of message | A `msgtype` `com.acme.order`, with a `body`; render it with `registerMsgtype()` | Its `body`. |
| A block on messages | A key `com.acme.tracking` in the content of your server's messages | The message as it is. |
| Something a user does | An event type `com.acme.order.cancel`: `ChatBackend.event_types`, `validate_content`, `on_event` | Nothing (ignored). |
| Something that happens | `services.ephemeral(conversation, "com.acme.progress", {…})`, or a timeline event (`services.send(…, type=…)`) | Nothing. |
| A feature of some conversations | A capability `com.acme.orders: {…}` | Off. |
| A kind of participant, a state, a composer mode | A namespaced value | `contact` / as unknown / `closed`. |

Guidelines: gate behaviour behind a capability; give content a `body`;
version what you add in its capability; and when it's useful beyond you,
propose it to Matrix as an [MSC](https://spec.matrix.org/proposals/).

## 10. WhatsApp, and other channels

An integration (a webhook, a bridge) turns a channel's messages into these
events, through `django_chat_ui.services`. For WhatsApp's Cloud API:

| WhatsApp | Here |
|---|---|
| `text` | `m.text` (`content.text`) |
| `image`, `video`, `audio` (voice), `document`, `sticker` | `m.image`, `m.video`, `m.audio` (+ voice), `m.file`, `m.image` — the file uploaded as media |
| `location` | `m.location` (`content.location`) |
| `contacts` | `…chat.contact` (`content.contact`) |
| `interactive` (reply buttons, lists) | The `buttons` block (`content.text(…, buttons=…)`); the customer's choice, an answer with `action` |
| `template` | `…chat.template` (`content.template`); outside the 24-hour window, `composer.mode: "templates"` |
| `reaction` | `m.reaction` (`services.react`) |
| Statuses `sent`, `delivered`, `read`, `failed` | Sent; `services.delivered()`; `services.read()`; `services.status(message, "failed", error)` |
| `context` (a reply) | `m.in_reply_to` |

## 11. Examples

### 11.1 A chatbot with quick replies, answering as it writes

```json
{"type": "m.room.message", "sender": "@p9:shop.example", "content": {"msgtype": "m.text", "body": "Hi! How can I help?\n\n• My order", "io.github.rodolvbg.chat.buttons": {"body": "Hi! How can I help?", "buttons": [{"id": "order", "label": "My order"}]}}}
{"type": "m.room.message", "sender": "@p4:shop.example", "content": {"msgtype": "m.text", "body": "My order", "io.github.rodolvbg.chat.action": {"event_id": "$41", "button": "order"}, "m.relates_to": {"m.in_reply_to": {"event_id": "$41"}}}}
{"type": "m.typing", "content": {"user_ids": ["@p9:shop.example"]}}
{"type": "io.github.rodolvbg.chat.stream", "content": {"id": "s1", "sender": "@p9:shop.example", "body": "Your order ships", "markdown": true}}
{"type": "m.room.message", "sender": "@p9:shop.example", "content": {"msgtype": "m.text", "body": "Your order ships today.", "io.github.rodolvbg.chat.stream": {"id": "s1"}}}
```

### 11.2 WhatsApp: the 24-hour window closes

```json
{"type": "io.github.rodolvbg.chat.capabilities", "state_key": "", "content": {"receipts": true, "composer": {
  "mode": "templates",
  "reason": "More than 24 hours since the customer's last message.",
  "templates": [{"id": "followup", "name": "Follow-up", "preview": "Hi {{1}}, can we help with anything else?", "params": ["name"]}]
}}}
```

```json
PUT /rooms/!7:shop.example/send/m.room.message/t12
{"msgtype": "io.github.rodolvbg.chat.template", "body": "Hi Anna, can we help with anything else?", "io.github.rodolvbg.chat.template": {"id": "followup", "params": {"name": "Anna"}}}
```

### 11.3 A site's own kind of message

```json
{"msgtype": "com.acme.order", "body": "Order A-1029 · 2 items · €59.90", "com.acme.order": {"id": "A-1029", "total": "59.90", "currency": "EUR"}}
```

A client that registered `com.acme.order` renders the order; any other
shows "Order A-1029 · 2 items · €59.90".
