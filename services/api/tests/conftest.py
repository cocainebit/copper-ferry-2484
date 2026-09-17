import os

os.environ["DEV_MODE"] = "true"
os.environ["DATABASE_URL"] = "sqlite://"
import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import sessionmaker

from desktop_service import db as models
from desktop_service.main import app


@pytest.fixture(autouse=True)
def isolated_platform(monkeypatch):
    """Tests never inherit the developer's platform configuration from .env."""
    from desktop_service.config import settings

    monkeypatch.setattr(settings(), "platform_url", "")
    monkeypatch.setattr(settings(), "platform_service_token", "")


@pytest.fixture
def db(tmp_path, monkeypatch):
    engine = models.make_engine("sqlite:///" + str(tmp_path / "test.db"))
    models.Base.metadata.create_all(engine)
    factory = sessionmaker(engine, expire_on_commit=False)
    monkeypatch.setattr(models, "Session", factory)

    def override():
        with factory() as session:
            yield session

    app.dependency_overrides[models.database] = override
    with factory() as session:
        session.add(models.ServiceHeartbeat(id="desktop-worker"))
        session.add(models.Workspace(id="w", name="Test", subscription="active", included=6000))
        session.add(models.Workspace(id="other", name="Other", subscription="active", included=6000))
        session.flush()
        session.add(models.Member(workspace_id="w", user_id="local-user", email="you@localhost", role="owner"))
        session.add(
            models.Member(workspace_id="other", user_id="another-user", email="other@example.com", role="owner")
        )
        session.commit()
        yield session
    app.dependency_overrides.clear()
    engine.dispose()


@pytest.fixture
def client(db):
    return TestClient(app, headers={"Authorization": "Bearer local-development-only"})
