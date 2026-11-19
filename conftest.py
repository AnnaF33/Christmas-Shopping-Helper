import pytest


@pytest.fixture(autouse=True)
def _own_database(tmp_path, monkeypatch):
    """Every test gets a fresh, throwaway database file."""
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path / 'test.db'}")
    for name in ("SHOP_SECRET_KEY", "SHOP_PROFILE_ID", "RENDER", "RENDER_EXTERNAL_URL", "SECRET_KEY"):
        monkeypatch.delenv(name, raising=False)
