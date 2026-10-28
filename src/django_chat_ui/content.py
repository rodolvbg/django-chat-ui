"""The contents of messages (``m.room.message``), to send with
``services.send()``: Matrix's message types, and this package's — each with
its ``body``, what any other Matrix client shows of it.

    from django_chat_ui import content, services

    services.send(conversation, bot, content.text(
        "How can I help?", buttons=[{"id": "order", "label": "My order"}]
    ))
"""

from __future__ import annotations

import html
from typing import Any

from .matrix import (
    BUTTONS,
    CARD,
    CONTACT,
    HTML,
    LINK,
    SYSTEM,
    TEMPLATE,
    markdown_html,
    plain,
)

Button = dict[str, Any]


def _label(button: Button) -> str:
    return str(button.get("label", button.get("id", "")))


def _link_url(button: Button) -> str | None:
    """A link button's URL (``https:``, or a path of this site); None: a
    quick reply."""
    url = button.get("url")
    if url is None:
        return None
    if not isinstance(url, str) or not (
        url.startswith("https://") or (url.startswith("/") and not url.startswith("//"))
    ):
        raise ValueError(f"A button's url is https: or a path, not {url!r}.")
    return url


def _option(button: Button) -> str:
    url = _link_url(button)
    return f"{_label(button)}: {url}" if url else _label(button)


def _option_html(button: Button) -> str:
    label = html.escape(_label(button), quote=False)
    url = _link_url(button)
    return f'<a href="{html.escape(url)}">{label}</a>' if url else label


def _with_buttons(
    content: dict[str, Any], buttons: list[Button] | None, persist: bool
) -> dict[str, Any]:
    """Quick replies under a message: this package's block (with the text
    before them, which its clients show), and their labels in ``body`` and
    ``formatted_body`` (a client without them answers by writing one). A
    button with a ``url`` is a link: there, it's the label and its URL."""
    if not buttons:
        return content
    block: dict[str, Any] = {"buttons": buttons, "body": content["body"]}
    if persist:
        block["persist"] = True
    options = "\n".join(f"• {_option(button)}" for button in buttons)
    content["body"] = f"{content['body']}\n\n{options}" if content["body"] else options
    if "formatted_body" in content:
        block["formatted_body"] = content["formatted_body"]
        items = "".join(f"<li>{_option_html(button)}</li>" for button in buttons)
        content["formatted_body"] += f"<ul>{items}</ul>"
    content[BUTTONS] = block
    return content


def text(
    body: str,
    *,
    markdown: bool = False,
    buttons: list[Button] | None = None,
    persist: bool = False,
    msgtype: str = "m.text",
) -> dict[str, Any]:
    """A text (``markdown``: with its HTML, ``formatted_body``), and quick
    replies (``buttons``: ``[{"id", "label", "style"?}]``; ``persist``: they
    stay usable after another message). A button with a ``url``
    (``https:``, or a path of this site) opens it instead: ``{"label",
    "url", "style"?}``, always usable, and nothing is sent."""
    content: dict[str, Any] = {"msgtype": msgtype, "body": body}
    if markdown:
        content.update(
            body=plain(body), format=HTML, formatted_body=markdown_html(body)
        )
    return _with_buttons(content, buttons, persist)


def notice(body: str, **options: Any) -> dict[str, Any]:
    """What a bot says (``m.notice``: clients never answer it automatically)."""
    return text(body, msgtype="m.notice", **options)


def system(body: str, code: str = "") -> dict[str, Any]:
    """An event in the thread: "Ana joined", "Assigned to support"."""
    return {"msgtype": "m.notice", "body": body, SYSTEM: {"code": code} if code else {}}


def _info(**values: Any) -> dict[str, Any]:
    return {key: value for key, value in values.items() if value not in (None, "")}


def image(
    url: str,
    *,
    body: str = "",
    mimetype: str = "",
    size: int | None = None,
    width: int | None = None,
    height: int | None = None,
) -> dict[str, Any]:
    """``url``: an ``mxc://`` URI (or an ``https:`` one, which only this
    package's clients show)."""
    return {
        "msgtype": "m.image",
        "body": body or url,
        "url": url,
        "info": _info(mimetype=mimetype, size=size, w=width, h=height),
    }


def file(
    url: str, *, name: str, mimetype: str = "", size: int | None = None
) -> dict[str, Any]:
    return {
        "msgtype": "m.file",
        "body": name,
        "filename": name,
        "url": url,
        "info": _info(mimetype=mimetype, size=size),
    }


def video(
    url: str, *, body: str = "", mimetype: str = "", size: int | None = None
) -> dict[str, Any]:
    return {
        "msgtype": "m.video",
        "body": body or url,
        "url": url,
        "info": _info(mimetype=mimetype, size=size),
    }


def audio(
    url: str,
    *,
    body: str = "",
    mimetype: str = "",
    size: int | None = None,
    voice: bool = False,
) -> dict[str, Any]:
    content: dict[str, Any] = {
        "msgtype": "m.audio",
        "body": body or url,
        "url": url,
        "info": _info(mimetype=mimetype, size=size),
    }
    if voice:
        content["org.matrix.msc3245.voice"] = {}
    return content


def location(
    lat: float, lng: float, *, name: str = "", address: str = ""
) -> dict[str, Any]:
    content: dict[str, Any] = {
        "msgtype": "m.location",
        "body": "\n".join(v for v in (name, address) if v) or f"{lat}, {lng}",
        "geo_uri": f"geo:{lat},{lng}",
    }
    if name or address:
        content[LINK] = _info(title=name, description=address)
    return content


def contact(
    name: str, *, phones: list[str] | None = None, emails: list[str] | None = None
) -> dict[str, Any]:
    """A shared contact card."""
    phones, emails = phones or [], emails or []
    return {
        "msgtype": CONTACT,
        "body": "\n".join([name, *phones, *emails]),
        CONTACT: {"name": name, "phones": phones, "emails": emails},
    }


def link(
    url: str, *, title: str = "", description: str = "", image: str = ""
) -> dict[str, Any]:
    """A link, with its preview."""
    return {
        "msgtype": "m.text",
        "body": "\n".join(v for v in (title, url) if v),
        LINK: _info(url=url, title=title, description=description, image=image),
    }


def card(
    title: str = "",
    *,
    text: str = "",
    image: str = "",
    url: str = "",
    buttons: list[Button] | None = None,
) -> dict[str, Any]:
    """A rich card, as bots send: a title, a text, an image, a link and
    buttons."""
    body = "\n".join(v for v in (title, text, url) if v)
    content: dict[str, Any] = {
        "msgtype": CARD,
        "body": body,
        CARD: _info(title=title, text=text, image=image, url=url),
    }
    return _with_buttons(content, buttons, False)


def template(template_id: str, params: dict[str, str], body: str) -> dict[str, Any]:
    """A pre-approved message (WhatsApp's, outside its 24-hour window):
    ``body`` is its text, filled in."""
    return {
        "msgtype": TEMPLATE,
        "body": body,
        TEMPLATE: {"id": template_id, "params": params},
    }
