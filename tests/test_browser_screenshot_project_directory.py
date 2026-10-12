from agent.tools.browser.browser_service import BrowserService


def test_screenshot_directory_follows_each_project(tmp_path):
    service = BrowserService.__new__(BrowserService)
    service._screenshot_dir = None
    first = tmp_path / 'first'
    second = tmp_path / 'second'
    first.mkdir()
    second.mkdir()
    assert service._get_screenshot_dir(str(first)) == str(first / 'tmp')
    assert service._get_screenshot_dir(str(second)) == str(second / 'tmp')
    assert (second / 'tmp').is_dir()


def test_screenshot_directory_tracks_default_working_directory(tmp_path, monkeypatch):
    service = BrowserService.__new__(BrowserService)
    service._screenshot_dir = None
    service._get_screenshot_dir(str(tmp_path / 'previous'))
    monkeypatch.chdir(tmp_path)
    assert service._get_screenshot_dir() == str(tmp_path / 'tmp')
