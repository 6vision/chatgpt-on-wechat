import pytest
from agent.tools.edit.edit import Edit


@pytest.mark.parametrize('ending', ['\r', '\r\n', '\n'])
def test_edit_retains_original_line_separators(tmp_path, ending):
    path = tmp_path / 'sample.txt'
    path.write_bytes(f'alpha{ending}beta{ending}gamma{ending}'.encode())
    result = Edit({'cwd': str(tmp_path)}).execute({'path': 'sample.txt', 'oldText': 'beta', 'newText': 'updated'})
    assert result.status == 'success'
    assert path.read_bytes() == f'alpha{ending}updated{ending}gamma{ending}'.encode()
