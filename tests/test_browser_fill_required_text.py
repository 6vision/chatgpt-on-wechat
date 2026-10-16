import pytest
from agent.tools.browser.browser_tool import BrowserTool


@pytest.mark.parametrize('arguments', [{'selector': '#input'}, {'selector': '#input', 'text': None}, {'selector': '#input', 'text': 42}])
def test_missing_or_invalid_fill_text_does_not_touch_input(monkeypatch, arguments):
    tool = BrowserTool()
    def unexpected_service():
        raise AssertionError('Invalid fill must not access browser')
    monkeypatch.setattr(tool, '_get_service', unexpected_service)
    result = tool._do_fill(arguments)
    assert result.status == 'error'
    assert 'text' in result.result


def test_explicit_empty_text_still_clears_input(monkeypatch):
    tool = BrowserTool()
    calls = []
    class Service:
        def fill(self, text, **kwargs):
            calls.append(text)
            return {'filled': True}
    monkeypatch.setattr(tool, '_get_service', lambda: Service())
    assert tool._do_fill({'selector': '#input', 'text': ''}).status == 'success'
    assert calls == ['']
