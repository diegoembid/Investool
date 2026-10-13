"""Lógica de acceso: contraseña (Argon2id) + doble factor (TOTP) + sesiones."""

import contextlib
import hashlib
import secrets
from dataclasses import dataclass
from datetime import timedelta

import pyotp
from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError
from sqlalchemy import delete, func, or_, select, text, update
from sqlalchemy.orm import Session

from app.core import crypto
from app.core.config import Settings
from app.core.db import utcnow
from app.modules.auth.models import AuthSession, LoginAttempt, User

_hasher = PasswordHasher()
# Hash ficticio para que un correo inexistente tarde lo mismo que uno real.
_DUMMY_HASH = _hasher.hash("contraseña-ficticia-para-igualar-tiempos")

MIN_PASSWORD_LENGTH = 12
TOTP_ISSUER = "Investool"


class LoginLocked(Exception):
    pass


class InvalidCredentials(Exception):
    pass


class UserAlreadyExists(Exception):
    pass


@dataclass
class NewUser:
    user: User
    totp_secret: str
    provisioning_uri: str


def normalize_email(email: str) -> str:
    return email.strip().lower()


def validate_password(password: str) -> None:
    if len(password) < MIN_PASSWORD_LENGTH:
        raise ValueError(f"La contraseña debe tener al menos {MIN_PASSWORD_LENGTH} caracteres")


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def create_user(db: Session, email: str, password: str, replace: bool = False) -> NewUser:
    """Crea el usuario (o lo reemplaza) con una semilla TOTP nueva."""
    validate_password(password)
    email = normalize_email(email)
    existing = db.scalar(select(User).where(User.email == email))
    if existing and not replace:
        raise UserAlreadyExists(email)

    secret = pyotp.random_base32()
    if existing:
        user = existing
        user.password_hash = _hasher.hash(password)
        user.totp_secret_encrypted = crypto.encrypt(secret)
        user.totp_last_step = None
        # Cerrar todas las sesiones abiertas al restablecer credenciales.
        for s in db.scalars(select(AuthSession).where(AuthSession.user_id == user.id)):
            s.revoked_at = utcnow()
        clear_login_failures(db, email)
    else:
        user = User(
            email=email,
            password_hash=_hasher.hash(password),
            totp_secret_encrypted=crypto.encrypt(secret),
        )
        db.add(user)
    db.flush()
    uri = pyotp.TOTP(secret).provisioning_uri(name=email, issuer_name=TOTP_ISSUER)
    return NewUser(user=user, totp_secret=secret, provisioning_uri=uri)


def _recent_failures(db: Session, email: str, settings: Settings) -> int:
    since = utcnow() - timedelta(minutes=settings.login_lockout_minutes)
    return (
        db.scalar(
            select(func.count(LoginAttempt.id)).where(
                LoginAttempt.email == email,
                LoginAttempt.success.is_(False),
                # Los intentos rechazados por bloqueo no cuentan: si contaran, el bloqueo
                # se alargaría solo mientras alguien siguiera intentándolo.
                LoginAttempt.reason != "locked",
                LoginAttempt.created_at >= since,
            )
        )
        or 0
    )


def _verify_totp(user: User, code: str) -> int | None:
    """Devuelve el intervalo TOTP aceptado, o None si el código no vale."""
    code = code.strip().replace(" ", "")
    if not (code.isdigit() and len(code) == 6):
        return None
    totp = pyotp.TOTP(crypto.decrypt(user.totp_secret_encrypted))
    now_step = totp.timecode(utcnow())
    # Se admite un intervalo de margen (30 s) por desfase de reloj.
    for step in (now_step - 1, now_step, now_step + 1):
        if secrets.compare_digest(totp.generate_otp(step), code):
            if user.totp_last_step is not None and step <= user.totp_last_step:
                return None  # código ya usado
            return step
    return None


def _lock_email(db: Session, email: str) -> None:
    """Serializa los intentos de acceso de un mismo correo (bloqueo de PostgreSQL que se
    libera al terminar la transacción), para que el recuento de fallos y el uso único del
    código TOTP no se puedan saltar con peticiones simultáneas."""
    key = int.from_bytes(hashlib.sha256(email.encode()).digest()[:8], "big", signed=True)
    db.execute(text("SELECT pg_advisory_xact_lock(:k)"), {"k": key})


def _claim_totp_step(db: Session, user: User, step: int) -> bool:
    """Marca el intervalo TOTP como usado; falla si otro acceso ya lo usó."""
    result = db.execute(
        update(User)
        .where(
            User.id == user.id,
            or_(User.totp_last_step.is_(None), User.totp_last_step < step),
        )
        .values(totp_last_step=step)
        .execution_options(synchronize_session=False)
    )
    if result.rowcount != 1:
        return False
    user.totp_last_step = step
    return True


def clear_login_failures(db: Session, email: str) -> int:
    """Desbloquea el acceso de un correo borrando sus intentos fallidos."""
    result = db.execute(
        delete(LoginAttempt).where(
            LoginAttempt.email == normalize_email(email), LoginAttempt.success.is_(False)
        )
    )
    return result.rowcount or 0


def authenticate(db: Session, settings: Settings, email: str, password: str, code: str) -> User:
    email = normalize_email(email)
    _lock_email(db, email)
    if _recent_failures(db, email, settings) >= settings.login_max_failures:
        db.add(LoginAttempt(email=email, success=False, reason="locked"))
        db.commit()
        raise LoginLocked()

    user = db.scalar(select(User).where(User.email == email, User.is_active.is_(True)))
    reason = None
    if user is None:
        with contextlib.suppress(VerificationError):
            _hasher.verify(_DUMMY_HASH, password)
        reason = "unknown_user"
    else:
        try:
            _hasher.verify(user.password_hash, password)
        except (VerificationError, InvalidHashError):
            reason = "bad_password"
        else:
            step = _verify_totp(user, code)
            if step is None or not _claim_totp_step(db, user, step):
                reason = "bad_totp"
            else:
                if _hasher.check_needs_rehash(user.password_hash):
                    user.password_hash = _hasher.hash(password)

    if reason:
        db.add(
            LoginAttempt(
                email=email, user_id=user.id if user else None, success=False, reason=reason
            )
        )
        db.commit()
        raise InvalidCredentials()

    assert user is not None
    db.add(LoginAttempt(email=email, user_id=user.id, success=True, reason="ok"))
    return user


def start_session(db: Session, settings: Settings, user: User, user_agent: str | None) -> str:
    token = secrets.token_urlsafe(32)
    db.add(
        AuthSession(
            user_id=user.id,
            token_hash=hash_token(token),
            expires_at=utcnow() + timedelta(hours=settings.session_hours),
            user_agent=(user_agent or "")[:255],
        )
    )
    db.commit()
    return token


def user_for_token(db: Session, token: str) -> User | None:
    session = db.scalar(
        select(AuthSession).where(
            AuthSession.token_hash == hash_token(token),
            AuthSession.revoked_at.is_(None),
            AuthSession.expires_at > utcnow(),
        )
    )
    if session is None:
        return None
    user = db.get(User, session.user_id)
    if user is None or not user.is_active:
        return None
    return user


def end_session(db: Session, token: str) -> None:
    session = db.scalar(select(AuthSession).where(AuthSession.token_hash == hash_token(token)))
    if session and session.revoked_at is None:
        session.revoked_at = utcnow()
        db.commit()
