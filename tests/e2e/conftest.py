import pytest
from playwright.sync_api import Browser


@pytest.fixture
def new_page(browser: Browser):
    """Pages of their own contexts (their own cookies), closed after the
    test: an open page keeps its chat's stream connecting to the server."""
    contexts = []

    def new(**options):
        context = browser.new_context(**options)
        contexts.append(context)
        return context.new_page()

    yield new
    for context in contexts:
        context.close()
