# django-chat-ui

A reusable chat interface — WhatsApp, a chatbot, a company's internal
chat, a "contact us" widget — over one protocol, and a Django backend for
it. Work in progress.

- [The protocol](docs/protocol.md) (and its [JSON Schema](docs/protocol.schema.json)):
  the contract between the interface and any backend, designed to be
  extended.
- `<chat-thread>`: one conversation, its composer following the
  conversation's capabilities (free text, templates only, buttons only,
  closed). Vanilla JS, no build step, safe under a strict Content Security
  Policy.
- `<chat-inbox>`: the inbox of whoever answers — every conversation, the
  latest active first, with unread counts and a search, and the one
  selected; on a narrow screen, the list or the conversation.
- `<chat-widget>`: a site's floating "contact us" chat, which starts a
  conversation when opened (and can remember it, with `storage-key`).
- A Django app: the conversations in the database, the protocol over
  Server-Sent Events and HTTP (or polling), attachments, a backend class to
  decide who chats and what happens, and the texts translated (English and
  Spanish).

![The staff's inbox: the conversations, and one with a visitor, whom an assistant answered before an agent joined](docs/screenshots/inbox.png)

The same conversation, from the site's widget:

![The "contact us" widget open on a shop's page](docs/screenshots/widget.png)

WhatsApp's 24-hour window closed, the composer offers only templates; on a
phone, the inbox shows the list or the conversation; and it follows the
system's dark mode:

![Only templates can be sent to Anna](docs/screenshots/templates.png)

![The inbox on a phone: the list, and a conversation](docs/screenshots/mobile.png)

![The inbox, dark](docs/screenshots/inbox-dark.png)

Reactions, where a conversation allows them (here, only some emojis):

![Reactions to a message of the team, and the picker open on another](docs/screenshots/reactions.png)

## With Django

```bash
pip install django-chat-ui
```

```python
INSTALLED_APPS = [..., "django_chat_ui"]

urlpatterns = [..., path("chat/", include("django_chat_ui.urls"))]
```

```bash
python manage.py migrate
```

Then, in a template, `{% chat_ui %}` in the `<head>` and the components
wherever they go:

```django
{% load chat_ui %}
<head>
  …
  {% chat_ui %}
</head>
<body>
  <chat-inbox></chat-inbox>          {# the staff's inbox #}
  <chat-widget heading="Support" subheading="We answer in minutes"
               storage-key="support"></chat-widget>   {# the visitors' #}
</body>
```

`{% chat_ui %}` writes the stylesheet, the configuration (endpoints, CSRF
token, the texts in the request's language) as a JSON data block, and the
module that connects every component of the page. Nothing inline runs: it
works under a strict Content Security Policy. `{% chat_ui transport="polling" %}`
polls instead of keeping a connection open, and `transport="websocket"`
speaks over a WebSocket (below).

The server sends each client what it said it can show (in its `hello`): a
client without cards gets their text, one without markdown plain text, one
that doesn't stream the finished message.

### Who chats, and what happens

Out of the box, logged-in users chat (staff as agents), each sees the
conversations they take part in, and a conversation started from the
widget goes to every active staff user, `pending` until one answers.
Everything else is a site's to decide, in a subclass of `ChatBackend`:

```python
# myapp/chat.py
from django_chat_ui import services
from django_chat_ui.backend import ChatBackend


class Backend(ChatBackend):
    allow_anonymous = True  # visitors who aren't logged in
    hooks = "thread"  # on_message & co. after the command is answered

    def support_team(self, channel):
        return [self.participant_for_user(user) for user in on_duty()]

    def on_start(self, request, conversation, participant):
        services.system(conversation, "We'll be with you in a minute.")

    def before_send(self, request, conversation, participant, parts):
        if participant.kind == "agent" and conversation.state == "pending":
            services.update_conversation(conversation, state="open")
            services.system(conversation, f"{participant.name} joined")

    def on_message(self, request, message):
        notify_whatsapp(message)
```

```python
CHAT_UI = {"BACKEND": "myapp.chat.Backend"}
```

Reactions are off unless a conversation's capabilities turn them on:
`"reactions": True` (any emoji; the interface offers a few), or
`"reactions": {"emojis": ["👍", "✅", "👀"]}` (only those). In
`new_capabilities()` for the conversations it starts, or for any one with
`services.update_conversation(conversation, capabilities={"reactions": True})`.

Its hooks: `get_participant`, `conversations`, `can_start`, `start`,
`support_team`, `new_capabilities`, `before_send`, `on_start`,
`on_message`, `on_action`, `validate_parts`, `session_capabilities`, and
`commands` for the commands of extensions.

`on_start`, `on_message` and `on_action` react to a command. With
`hooks = "inline"` (the default) they run inside its request; with
`hooks = "thread"`, in a thread of their own once it's committed, so a bot
that takes seconds doesn't hold the message that was sent. For a task
queue (Celery, `django.tasks`), override `run_hook(hook, *args)`.

### Your own models

Conversations and participants can be a site's own models, with its
fields: who a conversation is assigned to, its priority, the company of a
contact. Subclass the abstract ones, and name them in the settings
**before the first `migrate`** (like `AUTH_USER_MODEL`, they can't be
swapped afterwards without migrating the data by hand):

```python
# helpdesk/models.py
from django_chat_ui.models import AbstractConversation, AbstractParticipant


class Ticket(AbstractConversation):
    priority = models.IntegerField(default=1)
    assignee = models.ForeignKey(User, null=True, on_delete=models.SET_NULL)


class Contact(AbstractParticipant):
    company = models.CharField(max_length=200, blank=True)
```

```python
# settings.py
CHAT_UI_CONVERSATION_MODEL = "helpdesk.Ticket"
CHAT_UI_PARTICIPANT_MODEL = "helpdesk.Contact"
```

Both are optional (each defaults to the package's own). The messages,
memberships and attachments stay the package's, pointing to them. In code,
`get_conversation_model()` and `get_participant_model()` (from
`django_chat_ui.models`) give the models in use;
`services.create_conversation(..., priority=2)` fills the fields of yours.
Register them in the admin with `django_chat_ui.admin.ConversationAdmin`
and `ParticipantAdmin`.

For the interface to get your fields, add them in the backend, under
`ext` (with your namespace) or `meta`:

```python
class Backend(ChatBackend):
    def serialize_conversation(self, conversation, data):
        data["ext"] = {"helpdesk": {"priority": conversation.priority}}
        return data
```

The example does all this (`example/helpdesk`). Fields that don't need a
column (an id of a CRM, a tag) fit in the `ext` and `meta` JSON fields
every model already has; and a model of yours with a `OneToOneField` to
the conversation needs no setting at all.

### Integrations: `services`

Bots, webhooks and assignment rules change conversations through
`django_chat_ui.services`, which also tells every open interface:

```python
from django_chat_ui import services

message = services.post(conversation, bot, [{"type": "text", "text": "Hi"}])
services.update_message(message, status="delivered")  # a receipt

answer = services.start_stream(conversation, bot)  # a bot writing
services.delta(answer, "Your order ")
services.delta(answer, "ships today.")
services.finish(answer)

services.update_conversation(
    conversation,
    capabilities={
        "composer": {
            "mode": "templates",
            "templates": [...],  # WhatsApp's window closed
        }
    },
)
```

Also `create_conversation`, `add_participant`, `remove_participant`,
`system`, `typing`, `read`, and `emit` for the events of extensions.

### An AI that answers as it writes

Like ChatGPT's: the answer appears in its bubble as the model writes it.
`services.stream_text()` takes the chunks a model streams, sends them
together (every 0.1 s or 200 characters: a model's are a few letters each,
and each one sent is a row of the events), and finishes the message when
they end, or when they fail (with what came; the error goes on):

```python
import anthropic

client = anthropic.Anthropic()


class Backend(ChatBackend):
    hooks = "thread"  # the visitor's message is sent at once; the answer, after

    def on_message(self, request, message):
        if message.author.kind == "bot":
            return
        with client.messages.stream(
            model="claude-opus-5-5",
            max_tokens=1024,
            system="You are the assistant of a shop…",
            messages=history(message.conversation),  # your mapping of the messages
        ) as stream:
            services.stream_text(message.conversation, bot, stream.text_stream)
```

`then=[{"type": "buttons", ...}]` adds parts after the text (quick
replies), and `markdown=False` sends it as plain text. For the words to
flow rather than jump, read the events more often: `"POLL_INTERVAL": 0.1`.
A client that doesn't stream gets the finished message only.

### Settings

```python
CHAT_UI = {
    "BACKEND": "django_chat_ui.backend.ChatBackend",
    "STREAM_TIMEOUT": 25,  # seconds a stream lasts (the browser reconnects)
    "POLL_INTERVAL": 0.5,  # seconds between reads of new events
    "KEEPALIVE": 15,  # seconds of silence before a keep-alive comment
    "RETRY": 1000,  # milliseconds the browser waits to reconnect
    "SETTLE": 1.0,  # seconds an event missing in the sequence is waited for
}
```

Under WSGI each open stream holds a worker for up to `STREAM_TIMEOUT`;
under ASGI it waits without a thread. The events are kept in the database
for clients to resume; `python manage.py chat_ui_prune --days 7` deletes
the old ones (run it daily).

A chat writes from several requests at once. On SQLite, let transactions
take their lock when they start, or two at once fail with "database is
locked" (Django 5.1+):

```python
DATABASES = {"default": {..., "OPTIONS": {"transaction_mode": "IMMEDIATE"}}}
```

### WebSocket

With [Channels](https://channels.readthedocs.io/)
(`pip install django-chat-ui[channels]`) and an ASGI server:

```python
# asgi.py
from channels.auth import AuthMiddlewareStack
from channels.routing import ProtocolTypeRouter, URLRouter
from django.core.asgi import get_asgi_application

django_application = get_asgi_application()

from django_chat_ui.routing import websocket_urlpatterns  # noqa: E402

application = ProtocolTypeRouter(
    {
        "http": django_application,
        "websocket": AuthMiddlewareStack(URLRouter(websocket_urlpatterns)),
    }
)
```

and `{% chat_ui transport="websocket" %}`. The socket is at `chat/ws`, next
to the app's URLs included at `chat/`; elsewhere, route
`django_chat_ui.consumers.ChatConsumer.as_asgi()` at `<there>/ws`.

## Without Django

The components only speak the protocol: any backend that does works.

```html
<link rel="stylesheet" href="…/django_chat_ui/chat.css">
<chat-thread conversation="conv_1"></chat-thread>
<script type="module">
  import "…/django_chat_ui/chat-thread.js";
  import { ChatClient } from "…/django_chat_ui/client.js";
  import { HttpTransport } from "…/django_chat_ui/transports/http.js";
  // or WebSocketTransport, from transports/websocket.js

  const client = new ChatClient(new HttpTransport({ events: "/chat/events", commands: "/chat/commands" }));
  document.querySelector("chat-thread").client = client;
  await client.connect();
</script>
```

Each takes its texts, to translate them: `element.texts = { send: "Enviar" }`.
Theme them with the `--chat-*` custom properties (on the inbox or the
widget, they reach its thread), or `data-theme="light"`/`"dark"`.

Your own kinds of content render with `registerPart("acme.order", render)`;
any other client shows their `fallback` text.

## Demos

The components alone, on an in-memory server:

```bash
python -m http.server
# open http://localhost:8000/demo/
```

The Django example: a shop with the widget for its visitors (an assistant
greets them, streaming) and an inbox for its staff. With
`ANTHROPIC_API_KEY` set (and `pip install anthropic`), the assistant
answers what visitors write with Claude (`ANTHROPIC_MODEL` to choose
another model); without, it says someone will answer.

```bash
python example/manage.py migrate
python example/manage.py demo_chat     # conversations, and the users admin / demo
python example/manage.py runserver
# http://localhost:8000/ (visitor) and http://localhost:8000/inbox/ (staff)
# ?transport=polling to poll; over a WebSocket, under ASGI:
uvicorn --app-dir example example.asgi:application
# http://localhost:8000/?transport=websocket
```

## Development

```bash
uv sync
uv run playwright install chromium
uv run pytest                      # Python, with the end-to-end tests
npm install
npm test                           # vitest
npx biome check .
```
