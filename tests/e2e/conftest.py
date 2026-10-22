import time

import pytest
from playwright.sync_api import Browser


@pytest.fixture
def new_page(browser: Browser):
    """Pages of their own contexts (their own cookies), closed after the
    test: an open page keeps syncing. A long poll under way only ends when
    it times out (SYNC_TIMEOUT): it's waited for, not to read the database
    once the test is over."""
    contexts = []

    def new(**options):
        context = browser.new_context(**options)
        contexts.append(context)
        return context.new_page()

    yield new
    for context in contexts:
        context.close()
    if contexts:
        time.sleep(0.7)
