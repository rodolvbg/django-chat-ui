"""The contents of messages, and what other Matrix clients show of them."""

import pytest

from django_chat_ui import content
from django_chat_ui.matrix import BUTTONS, CARD, CONTACT, HTML, LINK, SYSTEM, TEMPLATE

MENU = [{"id": "a", "label": "Yes"}, {"id": "b", "label": "<No>"}]


def test_text():
    assert content.text("Hi") == {"msgtype": "m.text", "body": "Hi"}
    assert content.text("**Hi**", markdown=True) == {
        "msgtype": "m.text",
        "body": "Hi",
        "format": HTML,
        "formatted_body": "<p><strong>Hi</strong></p>",
    }
    assert content.notice("Hi")["msgtype"] == "m.notice"


def test_quick_replies_with_their_fallback():
    message = content.text("Pick:", buttons=MENU, persist=True)
    assert message["body"] == "Pick:\n\n• Yes\n• <No>"
    assert message[BUTTONS] == {"buttons": MENU, "body": "Pick:", "persist": True}

    formatted = content.text("*Pick*", markdown=True, buttons=MENU)
    assert formatted["formatted_body"] == (
        "<p><em>Pick</em></p><ul><li>Yes</li><li>&lt;No&gt;</li></ul>"
    )
    assert formatted[BUTTONS]["formatted_body"] == "<p><em>Pick</em></p>"
    assert "persist" not in formatted[BUTTONS]
    # Only buttons.
    assert content.text("", buttons=MENU)["body"] == "• Yes\n• <No>"


def test_system():
    assert content.system("Ana joined", "joined") == {
        "msgtype": "m.notice",
        "body": "Ana joined",
        SYSTEM: {"code": "joined"},
    }
    assert content.system("Hi")[SYSTEM] == {}


def test_files():
    assert content.image("mxc://localhost/a", width=2, height=3, size=9) == {
        "msgtype": "m.image",
        "body": "mxc://localhost/a",
        "url": "mxc://localhost/a",
        "info": {"size": 9, "w": 2, "h": 3},
    }
    assert content.file("mxc://x/a", name="a.pdf", mimetype="application/pdf") == {
        "msgtype": "m.file",
        "body": "a.pdf",
        "filename": "a.pdf",
        "url": "mxc://x/a",
        "info": {"mimetype": "application/pdf"},
    }
    assert content.video("u", body="v")["body"] == "v"
    assert content.audio("u")["msgtype"] == "m.audio"
    assert "org.matrix.msc3245.voice" in content.audio("u", voice=True)
    assert "org.matrix.msc3245.voice" not in content.audio("u")


def test_location_contact_link_card_template():
    assert content.location(1.5, 2, name="Shop", address="Main St") == {
        "msgtype": "m.location",
        "body": "Shop\nMain St",
        "geo_uri": "geo:1.5,2",
        LINK: {"title": "Shop", "description": "Main St"},
    }
    assert content.location(1, 2)["body"] == "1, 2"
    assert LINK not in content.location(1, 2)

    assert content.contact("Ana", phones=["1"]) == {
        "msgtype": CONTACT,
        "body": "Ana\n1",
        CONTACT: {"name": "Ana", "phones": ["1"], "emails": []},
    }
    assert content.link("https://a.b", title="A")[LINK] == {
        "url": "https://a.b",
        "title": "A",
    }
    card = content.card("Shirt", text="Blue", url="https://a.b", buttons=MENU)
    assert card["msgtype"] == CARD
    assert card["body"] == "Shirt\nBlue\nhttps://a.b\n\n• Yes\n• <No>"
    assert card[CARD] == {"title": "Shirt", "text": "Blue", "url": "https://a.b"}
    assert card[BUTTONS]["buttons"] == MENU

    assert content.template("t1", {"name": "Ana"}, "Hi Ana") == {
        "msgtype": TEMPLATE,
        "body": "Hi Ana",
        TEMPLATE: {"id": "t1", "params": {"name": "Ana"}},
    }


def test_link_buttons():
    links = [
        {"label": "Track <it>", "url": "https://track.example/?a=1&b=2"},
        {"label": "Invoice", "url": "/orders/1/invoice/"},
        {"id": "no", "label": "No"},
    ]
    message = content.text("*Your order*", markdown=True, buttons=links)
    assert message[BUTTONS]["buttons"] == links
    # Other clients: the label and its URL.
    assert message["body"] == (
        "Your order\n\n• Track <it>: https://track.example/?a=1&b=2"
        "\n• Invoice: /orders/1/invoice/\n• No"
    )
    assert message["formatted_body"].endswith(
        '<ul><li><a href="https://track.example/?a=1&amp;b=2">Track &lt;it&gt;</a>'
        '</li><li><a href="/orders/1/invoice/">Invoice</a></li><li>No</li></ul>'
    )


@pytest.mark.parametrize(
    "url", ["javascript:alert(1)", "http://plain.example", "//elsewhere.example", 3]
)
def test_link_buttons_only_https_or_a_path(url):
    with pytest.raises(ValueError, match="https: or a path"):
        content.text("Go", buttons=[{"label": "Go", "url": url}])
