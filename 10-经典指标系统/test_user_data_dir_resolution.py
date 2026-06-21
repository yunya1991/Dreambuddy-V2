import ml_trade_service as svc
import os


def test_user_data_dir_prefers_explicit_env(monkeypatch):
    monkeypatch.setenv("ML_USER_DATA_DIR", "/tmp/custom_user_data_dir")
    monkeypatch.setenv("AGENT_ENV", "prod")
    p = svc._user_data_dir()
    assert str(p).endswith("/tmp/custom_user_data_dir")


def test_user_data_dir_prefers_prod_for_prod_env(monkeypatch):
    monkeypatch.delenv("ML_USER_DATA_DIR", raising=False)
    monkeypatch.delenv("FT_USER_DATA_DIR", raising=False)
    monkeypatch.setenv("AGENT_ENV", "prod")
    p = svc._user_data_dir()
    assert p.name == "user_data_prod"


def test_reload_dotenv_runtime_reads_prod_env(monkeypatch):
    monkeypatch.delenv("ML_USER_DATA_DIR", raising=False)
    monkeypatch.delenv("FT_USER_DATA_DIR", raising=False)
    monkeypatch.setenv("AGENT_ENV", "prod")
    monkeypatch.delenv("ASTER_API_KEY", raising=False)
    out = svc._reload_dotenv_runtime(override=True, prune=False)
    assert any(str(s).endswith("user_data_prod/.env") for s in (out.get("sources") or []))
    assert str(os.environ.get("ASTER_API_KEY") or "").strip() != ""
