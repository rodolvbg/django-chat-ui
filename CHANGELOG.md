# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added

- Matrix as the protocol: the components are Matrix clients (`ChatClient`
  over the Client-Server API: `/sync` with long polling or polling, a local
  echo of what's sent, receipts, typing, reactions, media), and the Django
  app a Matrix homeserver without federation (docs/protocol.md): access
  tokens (`m.login.password`) or the site's session, rooms, their state,
  `/messages`, media, CORS. Tested with matrix-js-sdk.
- This package's extensions to Matrix, namespaced under
  `io.github.rodolvbg.chat`, each with a fallback any other client shows:
  the conversations' capabilities and channel, quick replies and their
  answers, cards, WhatsApp's templates, shared contacts, link previews,
  system notices, a `delivered` receipt, a message's `failed` status, and
  messages being written (an AI's), as ephemeral events; their JSON Schema.
- `<chat-thread>`, `<chat-inbox>` and `<chat-widget>`: web components without
  a build step, safe under a strict Content Security Policy (HTML of
  messages rebuilt from the specification's safe subset).
- `homeserver.js`: a scriptable Matrix homeserver in memory, for demos and
  tests.
- The Django app: conversations, participants and their events (Matrix
  rooms, users and events); `services` and `content` for integrations;
  `ChatBackend` to decide who chats and what happens (its hooks inline, in
  a thread, or wherever `run_hook()` sends them), with the event types and
  message types of a site's extensions; `{% chat_ui %}`; the admin;
  `chat_ui_prune`.
- A site's own models of conversations and participants
  (`CHAT_UI_CONVERSATION_MODEL`, `CHAT_UI_PARTICIPANT_MODEL`), subclasses
  of `AbstractConversation` and `AbstractParticipant`; their fields reach
  the clients through `ChatBackend.serialize_conversation()` and
  `serialize_participant()`.
- `services.stream_text()`: a message written as an AI model streams it,
  shown as it comes, sent when it ends or fails.
- `django_chat_ui.agui.AgUiAgent`: AI agents that speak AG-UI answer in a
  conversation, as they write.
- Light or dark as the page around them: Django's admin's theme, the
  `dark` class of Unfold and Tailwind, or the page's background, before the
  system's; following a theme switch (`theme.js`).
- Reactions, where a conversation's `reactions` capability allows them (any
  emoji, or a list).
- Spanish translation.
