# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added

- The chat UI protocol, version 1.0 (draft), and its JSON Schema.
- `<chat-thread>`, `<chat-inbox>` and `<chat-widget>`: web components over
  the protocol, without a build step, safe under a strict Content Security
  Policy.
- `ChatClient`, and its transports: in memory (with a fake server, for demos
  and tests), over HTTP (Server-Sent Events, or polling) and over a
  WebSocket.
- The Django app: models of conversations, participants, messages and
  attachments; the protocol's commands; the stream of events, resumable;
  `services` for integrations; `ChatBackend` to decide who chats and what
  happens (its hooks inline, in a thread, or wherever `run_hook()` sends
  them); `{% chat_ui %}`; the admin; `chat_ui_prune`.
- A site's own models of conversations and participants
  (`CHAT_UI_CONVERSATION_MODEL`, `CHAT_UI_PARTICIPANT_MODEL`), subclasses
  of `AbstractConversation` and `AbstractParticipant`; their fields reach
  the interface through `ChatBackend.serialize_conversation()` and
  `serialize_participant()`.
- `services.stream_text()`: a message written as an AI model streams it,
  its chunks sent together, finished when they end or fail.
- Reactions: shown under the messages, and added from a picker, in the
  conversations whose `reactions` capability allows them (any emoji, or a
  list).
- What the server sends is degraded for what each client says it renders.
- The WebSocket transport, with Channels (`django-chat-ui[channels]`).
- Spanish translation.
