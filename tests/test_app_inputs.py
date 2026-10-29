"""Switching between the two planners keeps both planners' inputs (Streamlit drops hidden widgets' values)."""

import os

import pytest

pytest.importorskip("streamlit.testing.v1")
from streamlit.testing.v1 import AppTest  # noqa: E402

APP = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "app.py")


def test_inputs_survive_switching_planners(monkeypatch):
    monkeypatch.setenv("BCPLANNER_STATELESS", "1")          # never touch data_cache/settings.json
    at = AppTest.from_file(APP, default_timeout=60).run()
    at.number_input(key="tickets").set_value(30).run()
    at.radio(key="mode").set_value("Normal").run()
    at.number_input(key="n_cat").set_value(123).run()
    at.radio(key="mode").set_value("Rare").run()
    assert at.number_input(key="tickets").value == 30
    at.radio(key="mode").set_value("Normal").run()
    assert at.number_input(key="n_cat").value == 123
    assert not at.exception
