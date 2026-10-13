"""Configuración de las pruebas.

Las pruebas usan una base de datos PostgreSQL real llamada `<nombre>_test`, que se crea
sola en el mismo servidor que DATABASE_URL y se migra con Alembic (así también se
prueban las migraciones). Nunca se toca la base de datos principal.
"""

import os
import threading
from collections.abc import Iterator

import pytest
from cryptography.fernet import Fernet
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url

_base = make_url(
    os.environ.get("DATABASE_URL", "postgresql+psycopg://investool:investool@db:5432/investool")
)
TEST_DB = f"{_base.database}_test"
TEST_URL = _base.set(database=TEST_DB).render_as_string(hide_password=False)

os.environ["DATABASE_URL"] = TEST_URL
os.environ["APP_SECRET_KEY"] = Fernet.generate_key().decode()
os.environ["ENVIRONMENT"] = "test"
os.environ["COOKIE_SECURE"] = "false"
os.environ["ALLOWED_HOSTS"] = "testserver,localhost"
os.environ["ANTHROPIC_API_KEY"] = ""
os.environ["OPENAI_API_KEY"] = ""
# Cualquier cliente real creado por error en una prueba apunta a un puerto cerrado.
os.environ["ANTHROPIC_BASE_URL"] = "http://127.0.0.1:9"
os.environ["OPENAI_BASE_URL"] = "http://127.0.0.1:9"


def _create_test_database() -> None:
    admin = create_engine(
        _base.set(database="postgres").render_as_string(hide_password=False),
        isolation_level="AUTOCOMMIT",
    )
    with admin.connect() as conn:
        exists = conn.scalar(text("SELECT 1 FROM pg_database WHERE datname = :n"), {"n": TEST_DB})
        if exists:
            conn.execute(text(f'DROP DATABASE "{TEST_DB}" WITH (FORCE)'))
        conn.execute(text(f'CREATE DATABASE "{TEST_DB}"'))
    admin.dispose()


@pytest.fixture(scope="session", autouse=True)
def _database() -> Iterator[None]:
    from alembic.config import Config

    from alembic import command

    _create_test_database()
    cfg = Config(os.path.join(os.path.dirname(__file__), "..", "alembic.ini"))
    cfg.set_main_option("script_location", os.path.join(os.path.dirname(__file__), "..", "alembic"))
    cfg.attributes["database_url"] = TEST_URL
    command.upgrade(cfg, "head")
    yield


@pytest.fixture(autouse=True)
def _clean_tables() -> Iterator[None]:
    from app.core.config import get_settings

    get_settings.cache_clear()
    yield
    from app.core.db import get_engine

    with get_engine().begin() as conn:
        conn.execute(
            text(
                "TRUNCATE ai_calls, ai_cache, auth_login_attempts, auth_sessions, users "
                "RESTART IDENTITY CASCADE"
            )
        )


@pytest.fixture
def settings():
    from app.core.config import get_settings

    return get_settings()


@pytest.fixture
def sessions():
    from app.core.db import get_sessionmaker

    return get_sessionmaker()


class FakeProvider:
    """Proveedor simulado: no hace llamadas reales."""

    def __init__(
        self,
        name: str = "anthropic",
        text: str = "OK",
        input_tokens: int = 1000,
        output_tokens: int = 500,
        delay: float = 0.0,
        error: Exception | None = None,
    ):
        from app.modules.ai_gateway.providers.base import CompletionResult

        self.name = name
        self.calls = 0
        self._result = CompletionResult(
            text=text,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            stop_reason="end_turn",
        )
        self._delay = delay
        self._error = error
        self._lock = threading.Lock()

    def complete(self, request):
        import time

        with self._lock:
            self.calls += 1
        if self._delay:
            time.sleep(self._delay)
        if self._error:
            raise self._error
        return self._result


@pytest.fixture
def fake_providers():
    return {"anthropic": FakeProvider("anthropic"), "openai": FakeProvider("openai")}


@pytest.fixture
def client(fake_providers):
    from fastapi.testclient import TestClient

    from app.main import app
    from app.modules.ai_gateway import router as ai_router

    app.dependency_overrides[ai_router.get_providers] = lambda: fake_providers
    with TestClient(app, headers={"x-investool-request": "1"}) as c:
        yield c
    app.dependency_overrides.clear()


@pytest.fixture
def user_credentials(sessions):
    """Crea un usuario y devuelve (correo, contraseña, semilla TOTP)."""
    from app.modules.auth import service

    with sessions() as db:
        new = service.create_user(db, "Diego@Example.com", "una-contraseña-larga-y-segura")
        db.commit()
        return ("diego@example.com", "una-contraseña-larga-y-segura", new.totp_secret)
