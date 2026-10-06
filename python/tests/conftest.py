"""Keep every offline test's generated outputs away from a real paper account."""
from pathlib import Path
import sys
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


@pytest.fixture(autouse=True)
def isolated_generated_outputs(tmp_path, monkeypatch):
    root = Path(__file__).resolve().parent.parent
    directory = tmp_path / 'outputs'
    directory.mkdir()
    monkeypatch.setenv('GREENLIGHT_DATA_DIR', str(directory))
    for module in list(sys.modules.values()):
        location = getattr(module, '__file__', None)
        if location and Path(location).resolve().is_relative_to(root) and hasattr(module, 'DATA_DIR'):
            monkeypatch.setattr(module, 'DATA_DIR', directory)
