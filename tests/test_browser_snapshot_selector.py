import os
import tempfile
from pathlib import Path
import pytest
from agent.tools.browser.browser_service import BrowserService


@pytest.fixture(scope='module')
def page():
    playwright = pytest.importorskip('playwright.sync_api')
    chrome = '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome'
    executable = os.environ.get('COW_TEST_BROWSER_EXECUTABLE', chrome)
    if not Path(executable).is_file():
        pytest.skip('Set COW_TEST_BROWSER_EXECUTABLE to an installed browser')
    with tempfile.TemporaryDirectory(prefix='cow-snapshot-test-') as profile:
        with playwright.sync_playwright() as driver:
            context = driver.chromium.launch_persistent_context(profile, executable_path=executable, headless=True, args=['--disable-background-networking', '--disable-component-update'])
            page = context.new_page()
            page.set_content('<main id="chosen"><button>Inside</button></main><aside><button>Outside</button></aside>')
            try:
                yield page
            finally:
                context.close()


def service(page):
    instance = BrowserService.__new__(BrowserService)
    instance._page = page
    instance._config = {}
    return instance


def test_snapshot_selector_scopes_actual_dom_and_references(page):
    result = service(page)._do_snapshot('#chosen')
    assert 'Inside' in result
    assert 'Outside' not in result
    assert page.evaluate('Object.keys(window.__cowRefMap).length') == 1


def test_default_snapshot_still_covers_full_document(page):
    result = service(page)._do_snapshot()
    assert 'Inside' in result
    assert 'Outside' in result
    assert page.evaluate('Object.keys(window.__cowRefMap).length') == 2


def test_missing_snapshot_selector_reports_error(page):
    assert 'Snapshot error' in service(page)._do_snapshot('#missing')
