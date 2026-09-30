from pathlib import Path

from streamlit.testing.v1 import AppTest

from core.engine import execute_run, start_run
from core.llm import MockLLM
from core.storage import LocalStore


def test_interface_pages_and_saved_artifacts(monkeypatch, tmp_path):
    monkeypatch.setenv("ANGELIS_STORAGE", "local")
    monkeypatch.setenv("ANGELIS_DATA_DIR", str(tmp_path))
    monkeypatch.delenv("APP_PASSWORD", raising=False)
    store = LocalStore(tmp_path)
    run_id = start_run(store, mock=True)
    execute_run(store, run_id, MockLLM())
    app = AppTest.from_file(str(Path(__file__).resolve().parents[1] / "app.py"), default_timeout=20).run()
    assert not app.exception
    for page in ["BACKLOG", "STRATEGY", "RESEARCH", "CONTENT", "ART", "TATTOO", "JOURNAL", "COSTS", "SETTINGS"]:
        app.sidebar.radio[0].set_value(page).run()
        assert not app.exception, f"Error on {page}: {app.exception}"


def test_password_guard_precedes_data_access(monkeypatch, tmp_path):
    monkeypatch.setenv("ANGELIS_STORAGE", "local")
    monkeypatch.setenv("ANGELIS_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("APP_PASSWORD", "личныйпароль")
    app = AppTest.from_file(str(Path(__file__).resolve().parents[1] / "app.py"), default_timeout=20).run()
    assert not app.exception
    assert not tmp_path.joinpath("workspace.json").exists()
    app.text_input[0].set_value("wrong")
    app.button[0].click().run()
    assert app.error[0].value == "Пароль не подходит"
    assert not tmp_path.joinpath("workspace.json").exists()
