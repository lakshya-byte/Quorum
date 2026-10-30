"""Streamlit smoke tests with AppTest: every page renders without exceptions, with data and with none."""
import pytest

pytest.importorskip("streamlit")
from streamlit.testing.v1 import AppTest

from tests.test_evals_pipeline import smoke_run  # noqa: F401  (session fixture: a real fake-mode run)

from pathlib import Path

PAGES_DIR = Path(__file__).resolve().parent.parent / "evals" / "ui" / "pages"
PAGES = ["overview", "dataset_page", "run_page", "results_page", "deepeval_page", "ragas_page", "compare_page", "export_page"]


def page(name, results_dir):
    import os

    os.environ["EVALS_RESULTS_DIR"] = str(results_dir)
    from evals.ui import common

    common.st.cache_data.clear()
    return AppTest.from_file(str(PAGES_DIR / f"{name}.py"), default_timeout=90).run()


@pytest.mark.parametrize("name", PAGES)
def test_page_renders_with_results(name, smoke_run):
    d, _ = smoke_run
    at = page(name, d)
    assert not at.exception, [e.value for e in at.exception]


def test_pages_have_content(smoke_run):
    d, s = smoke_run
    assert any("Overview" in t.value for t in page("overview", d).title)
    ov = page("overview", d)
    assert ov.metric and any("FAKE MODE" in w.value for w in ov.warning)
    assert any("needs_judge" in m.value or "skipped" in m.value.lower() for m in page("deepeval_page", d).warning)
    rg = page("ragas_page", d)
    assert rg.tabs and not rg.exception
    ds = page("dataset_page", d)
    assert any("validation passed" in x.value for x in ds.success)


def test_run_page_refuses_unavailable_mode(smoke_run, monkeypatch):
    d, _ = smoke_run
    for k in ("NEBIUS_API_KEY", "MODEL_NANO"):
        monkeypatch.delenv(k, raising=False)
    monkeypatch.setattr("app.config.load_env", lambda: None)
    at = page("run_page", d)
    at.radio[0].set_value("hybrid")
    at.button[0].click() if at.button else None
    at.run()
    assert not at.exception
    assert any("Refused" in e.value for e in at.error)


@pytest.mark.parametrize("name", ["overview", "results_page", "deepeval_page", "ragas_page", "compare_page", "export_page"])
def test_pages_show_empty_state(name, tmp_path):
    at = page(name, tmp_path)
    assert not at.exception
    assert any("No eval runs yet" in i.value or "at least two runs" in i.value for i in at.info)
