import pathlib
import sys

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

import state  # noqa: E402


@pytest.fixture
def cfg():
    """Replace state.cfg for one test; restore it afterwards."""
    saved = dict(state.cfg)
    state.cfg.clear()
    yield state.cfg
    state.cfg.clear()
    state.cfg.update(saved)
