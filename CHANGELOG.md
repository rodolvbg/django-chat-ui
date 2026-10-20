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
- What the server sends is degraded for what each client says it renders.
- The WebSocket transport, with Channels (`django-chat-ui[channels]`).
- Spanish translation.
