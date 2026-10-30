import subprocess
import sys

from evals.compat import ensure_ragas_importable, stubs_installed


def test_ragas_metrics_import_after_shim():
    st = ensure_ragas_importable()
    assert st["ok"], st
    import ragas.metrics as rm

    assert hasattr(rm, "NonLLMContextPrecisionWithReference") and hasattr(rm, "ToolCallF1")


def test_shim_works_in_a_fresh_interpreter_and_only_stubs_when_needed():
    code = ("from evals.compat import ensure_ragas_importable, stubs_installed\n"
            "r = ensure_ragas_importable(); import ragas.metrics\n"
            "print(r['ok'], stubs_installed())\n")
    out = subprocess.run([sys.executable, "-W", "ignore", "-c", code], capture_output=True, text=True,
                         cwd=__file__.rsplit("/tests/", 1)[0])
    assert out.stdout.startswith("True"), out.stderr[-500:]
    try:
        import langchain_community.chat_models.vertexai  # noqa: F401
        real = True
    except Exception:
        real = False
    if not real:
        assert "ChatVertexAI" in out.stdout
