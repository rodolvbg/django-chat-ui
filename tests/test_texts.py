"""The texts given to the components are exactly theirs."""

import re
from pathlib import Path

import pytest

from django_chat_ui.texts import INBOX, THREAD, WIDGET

STATIC = Path(__file__).parent.parent / "src/django_chat_ui/static/django_chat_ui"


def keys(file, name):
    source = (STATIC / file).read_text()
    block = re.search(rf"export const {name} = \{{(.*?)\n\}};", source, re.S).group(1)
    return dict(re.findall(r'^\s+(\w+): "(.*)",$', block, re.M))


@pytest.mark.parametrize(
    "texts, file, name",
    [
        (THREAD, "chat-thread.js", "TEXTS"),
        (INBOX, "chat-inbox.js", "INBOX_TEXTS"),
        (WIDGET, "chat-widget.js", "WIDGET_TEXTS"),
    ],
)
def test_same_keys_and_english(texts, file, name):
    js = keys(file, name)
    assert {key: str(value) for key, value in texts.items()} == js
