"""Órdenes de administración.

Uso (dentro de Docker):
    docker compose exec backend python -m app.cli <orden>

Órdenes:
    generate-secret      Genera la clave maestra y la contraseña de la base de datos
    create-user          Crea el usuario con contraseña y doble factor
    reset-user           Cambia contraseña y doble factor (cierra todas las sesiones)
    unlock-user          Desbloquea el acceso tras demasiados intentos fallidos
    ai-smoke-test        Hace una llamada mínima a cada proveedor de IA configurado
    ai-usage             Muestra el gasto de IA del mes
"""

import argparse
import getpass
import io
import sys
from datetime import UTC, datetime

import qrcode


def _print_qr(uri: str) -> None:
    qr = qrcode.QRCode(border=2)
    qr.add_data(uri)
    qr.make(fit=True)
    out = io.StringIO()
    qr.print_ascii(out=out, invert=True)
    print(out.getvalue())


def _ask_password() -> str:
    from app.modules.auth.service import MIN_PASSWORD_LENGTH

    while True:
        p1 = getpass.getpass(f"Contraseña (mínimo {MIN_PASSWORD_LENGTH} caracteres): ")
        p2 = getpass.getpass("Repite la contraseña: ")
        if p1 != p2:
            print("No coinciden. Vuelve a intentarlo.\n")
        elif len(p1) < MIN_PASSWORD_LENGTH:
            print("Demasiado corta.\n")
        else:
            return p1


def cmd_generate_secret(_: argparse.Namespace) -> int:
    import secrets

    from cryptography.fernet import Fernet

    print("Copia estas dos líneas en tu fichero .env (sustituyendo las que empiezan por")
    print("CAMBIAR) y guárdalas también en tu gestor de contraseñas:\n")
    print(f"APP_SECRET_KEY={Fernet.generate_key().decode()}")
    print(f"POSTGRES_PASSWORD={secrets.token_hex(24)}")
    print("\nSi se pierde APP_SECRET_KEY, habrá que volver a configurar el doble factor")
    print("con `reset-user`. No cambies POSTGRES_PASSWORD después de arrancar la base de")
    print("datos por primera vez.")
    return 0


def _create_or_reset(args: argparse.Namespace, replace: bool) -> int:
    import pyotp

    from app.core.db import get_sessionmaker
    from app.modules.auth import service

    email = args.email or input("Correo electrónico: ").strip()
    password = _ask_password()
    Session = get_sessionmaker()
    with Session() as db:
        try:
            new = service.create_user(db, email, password, replace=replace)
        except service.UserAlreadyExists:
            print("Ese usuario ya existe. Usa `reset-user` para cambiar sus credenciales.")
            return 1

        print("\nEscanea este código con tu app de autenticación")
        print("(Bitwarden Authenticator, Google Authenticator, Microsoft Authenticator...):\n")
        _print_qr(new.provisioning_uri)
        print("Si no puedes escanearlo, introduce a mano esta clave en la app:")
        print(f"  {new.totp_secret}\n")
        print("Guarda esta clave en tu gestor de contraseñas: permite recuperar el acceso.\n")

        totp = pyotp.TOTP(new.totp_secret)
        for _ in range(3):
            code = input("Escribe el código de 6 dígitos que muestra la app: ").strip()
            now_step = totp.timecode(datetime.now(UTC))
            step = next(
                (s for s in (now_step - 1, now_step, now_step + 1) if totp.generate_otp(s) == code),
                None,
            )
            if step is not None:
                # Este código ya no servirá para entrar en la web.
                new.user.totp_last_step = step
                db.commit()
                print(f"\nListo. Usuario {new.user.email} configurado.")
                return 0
            print("Código incorrecto. Comprueba que la hora del ordenador y del móvil es correcta.")
        db.rollback()
        print("No se ha guardado nada. Vuelve a ejecutar la orden.")
        return 1


def cmd_create_user(args: argparse.Namespace) -> int:
    return _create_or_reset(args, replace=False)


def cmd_reset_user(args: argparse.Namespace) -> int:
    from sqlalchemy import select

    from app.core.db import get_sessionmaker
    from app.modules.auth.models import User
    from app.modules.auth.service import normalize_email

    args.email = args.email or input("Correo electrónico del usuario: ").strip()
    with get_sessionmaker()() as db:
        if db.scalar(select(User).where(User.email == normalize_email(args.email))) is None:
            print("No existe ese usuario.")
            return 1
    return _create_or_reset(args, replace=True)


def cmd_unlock_user(args: argparse.Namespace) -> int:
    from app.core.db import get_sessionmaker
    from app.modules.auth.service import clear_login_failures

    email = args.email or input("Correo electrónico del usuario: ").strip()
    with get_sessionmaker()() as db:
        n = clear_login_failures(db, email)
        db.commit()
    print(f"Acceso desbloqueado ({n} intentos fallidos borrados).")
    return 0


def cmd_ai_smoke_test(args: argparse.Namespace) -> int:
    from app.core.config import get_settings
    from app.core.db import get_sessionmaker
    from app.modules.ai_gateway.gateway import AIGateway, build_providers
    from app.modules.ai_gateway.smoke import run_smoke_test

    settings = get_settings()
    providers = build_providers(settings)
    gateway = AIGateway(get_sessionmaker(), settings, providers)
    targets = [args.provider] if args.provider else ["anthropic", "openai"]
    failures = 0
    for p in targets:
        r = run_smoke_test(gateway, settings, p)
        mark = "OK " if r.ok else "ERROR"
        print(f"[{mark}] {r.provider:<10} {r.model:<20} coste {r.cost_usd:.6f} USD  {r.detail}")
        failures += 0 if r.ok else 1
    return 1 if failures else 0


def cmd_ai_usage(_: argparse.Namespace) -> int:
    from app.core.config import get_settings
    from app.core.db import get_sessionmaker
    from app.modules.ai_gateway.gateway import build_providers
    from app.modules.ai_gateway.usage import summarize

    settings = get_settings()
    with get_sessionmaker()() as db:
        s = summarize(db, settings, set(build_providers(settings)))
    fx = s.usd_to_eur
    print(f"IA {'activada' if s.ai_enabled else 'DESACTIVADA'}")
    print(f"Hoy:   {s.today_spent_usd:.4f} USD de {s.daily_cap_usd:.2f} USD")
    print(
        f"Mes:   {s.month_spent_usd:.4f} USD de {s.monthly_cap_usd:.2f} USD "
        f"(~{s.month_spent_usd * fx:.2f} EUR)"
    )
    for p in s.providers:
        estado = "configurado" if p.configured else "sin clave"
        print(
            f"  {p.provider:<10} {p.month_spent_usd:.4f} / {p.month_cap_usd:.2f} USD  "
            f"[{estado}]  llamadas: {p.calls_by_status or {}}"
        )
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m app.cli",
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("generate-secret").set_defaults(func=cmd_generate_secret)
    for name, fn in (
        ("create-user", cmd_create_user),
        ("reset-user", cmd_reset_user),
        ("unlock-user", cmd_unlock_user),
    ):
        p = sub.add_parser(name)
        p.add_argument("--email")
        p.set_defaults(func=fn)
    p = sub.add_parser("ai-smoke-test")
    p.add_argument("--provider", choices=["anthropic", "openai"])
    p.set_defaults(func=cmd_ai_smoke_test)
    sub.add_parser("ai-usage").set_defaults(func=cmd_ai_usage)
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
