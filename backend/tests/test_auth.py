import pyotp
import pytest
from sqlalchemy import select

from app.modules.auth import service
from app.modules.auth.models import AuthSession, User


def _login(client, email, password, code):
    return client.post("/api/auth/login", json={"email": email, "password": password, "code": code})


def test_acceso_correcto_y_sesion(client, user_credentials):
    email, password, secret = user_credentials
    r = _login(client, email, password, pyotp.TOTP(secret).now())
    assert r.status_code == 200 and r.json() == {"email": email}
    cookie = r.headers["set-cookie"].lower()
    assert "httponly" in cookie and "samesite=strict" in cookie
    assert client.get("/api/auth/me").json() == {"email": email}


def test_correo_sin_distinguir_mayusculas(client, user_credentials):
    email, password, secret = user_credentials
    r = _login(client, "  DIEGO@example.COM ", password, pyotp.TOTP(secret).now())
    assert r.status_code == 200


def test_contraseña_incorrecta(client, user_credentials):
    email, _, secret = user_credentials
    r = _login(client, email, "otra-contraseña-larga", pyotp.TOTP(secret).now())
    assert r.status_code == 401
    assert client.get("/api/auth/me").status_code == 401


def test_codigo_incorrecto(client, user_credentials):
    email, password, _ = user_credentials
    assert _login(client, email, password, "000000").status_code == 401


def test_un_codigo_no_se_puede_reutilizar(client, user_credentials):
    email, password, secret = user_credentials
    code = pyotp.TOTP(secret).now()
    assert _login(client, email, password, code).status_code == 200
    assert _login(client, email, password, code).status_code == 401


def test_bloqueo_tras_intentos_fallidos(client, user_credentials, settings):
    email, password, secret = user_credentials
    for _ in range(settings.login_max_failures):
        assert _login(client, email, "mala-contraseña-xx", "123456").status_code == 401
    # Incluso con credenciales correctas, la cuenta queda bloqueada un tiempo.
    assert _login(client, email, password, pyotp.TOTP(secret).now()).status_code == 429


def test_cerrar_sesion_la_invalida(client, user_credentials, sessions):
    email, password, secret = user_credentials
    _login(client, email, password, pyotp.TOTP(secret).now())
    cookie = client.cookies.get("investool_session")
    assert client.post("/api/auth/logout").status_code == 204
    client.cookies.set("investool_session", cookie)
    assert client.get("/api/auth/me").status_code == 401
    with sessions() as db:
        assert db.scalar(select(AuthSession)).revoked_at is not None


def test_peticiones_sin_cabecera_de_seguridad_se_rechazan(client, user_credentials):
    email, password, secret = user_credentials
    r = client.post(
        "/api/auth/login",
        json={"email": email, "password": password, "code": pyotp.TOTP(secret).now()},
        headers={"x-investool-request": ""},
    )
    assert r.status_code == 403


def test_la_semilla_2fa_se_guarda_cifrada(sessions, user_credentials):
    _, _, secret = user_credentials
    with sessions() as db:
        user = db.scalar(select(User))
        assert secret not in user.totp_secret_encrypted
        assert user.password_hash.startswith("$argon2id$")


def test_contraseña_corta_rechazada(sessions):
    with sessions() as db, pytest.raises(ValueError):
        service.create_user(db, "a@b.com", "corta")


def test_restablecer_credenciales_cierra_sesiones(client, user_credentials, sessions):
    email, password, secret = user_credentials
    _login(client, email, password, pyotp.TOTP(secret).now())
    with sessions() as db:
        service.create_user(db, email, "nueva-contraseña-larga", replace=True)
        db.commit()
    assert client.get("/api/auth/me").status_code == 401


def test_cookie_segura_en_produccion(client, user_credentials, settings):
    settings.cookie_secure = True
    email, password, secret = user_credentials
    r = _login(client, email, password, pyotp.TOTP(secret).now())
    assert "secure" in r.headers["set-cookie"].lower()


def _parallel(n, fn):
    import threading

    out: list = []
    threads = [threading.Thread(target=lambda: out.append(fn())) for _ in range(n)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    return out


def test_un_codigo_no_vale_dos_veces_ni_en_paralelo(user_credentials, sessions, settings):
    email, password, secret = user_credentials
    code = pyotp.TOTP(secret).now()

    def attempt():
        with sessions() as db:
            try:
                service.authenticate(db, settings, email, password, code)
                db.commit()
                return "ok"
            except service.InvalidCredentials:
                return "rechazado"

    assert sorted(_parallel(4, attempt)) == ["ok", "rechazado", "rechazado", "rechazado"]


def test_bloqueo_atomico_con_intentos_en_paralelo(user_credentials, sessions, settings):
    email, _, _ = user_credentials

    def attempt():
        with sessions() as db:
            try:
                service.authenticate(db, settings, email, "mala-contraseña-xx", "123456")
            except service.InvalidCredentials:
                return "fallo"
            except service.LoginLocked:
                return "bloqueado"

    results = _parallel(20, attempt)
    assert results.count("fallo") == settings.login_max_failures


def test_intentos_durante_el_bloqueo_no_lo_alargan(user_credentials, sessions, settings):
    from datetime import timedelta

    from app.core.db import utcnow
    from app.modules.auth.models import LoginAttempt

    email, password, secret = user_credentials
    with sessions() as db:
        old = utcnow() - timedelta(minutes=settings.login_lockout_minutes + 1)
        for _ in range(settings.login_max_failures):
            db.add(LoginAttempt(email=email, success=False, reason="bad_password", created_at=old))
        # Intentos recientes rechazados por el bloqueo: no deben contar.
        for _ in range(10):
            db.add(LoginAttempt(email=email, success=False, reason="locked"))
        db.commit()
        service.authenticate(db, settings, email, password, pyotp.TOTP(secret).now())


def test_desbloquear_borra_los_fallos(client, user_credentials, sessions, settings):
    email, password, secret = user_credentials
    for _ in range(settings.login_max_failures):
        _login(client, email, "mala-contraseña-xx", "123456")
    with sessions() as db:
        assert service.clear_login_failures(db, email) == settings.login_max_failures
        db.commit()
    assert _login(client, email, password, pyotp.TOTP(secret).now()).status_code == 200
