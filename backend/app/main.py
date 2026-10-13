from fastapi import Depends, FastAPI, Request
from fastapi.responses import JSONResponse
from sqlalchemy import text
from sqlalchemy.orm import Session

from app import models_registry  # noqa: F401  (registra todos los modelos)
from app.core.config import get_settings
from app.core.db import get_db
from app.modules.ai_gateway.router import router as ai_router
from app.modules.auth.router import router as auth_router

CSRF_HEADER = "x-investool-request"
UNSAFE_METHODS = {"POST", "PUT", "PATCH", "DELETE"}

app = FastAPI(
    title="Investool",
    version="0.1.0",
    # La documentación interactiva solo en local.
    docs_url="/api/docs" if get_settings().environment == "local" else None,
    redoc_url=None,
    openapi_url="/api/openapi.json" if get_settings().environment == "local" else None,
)


def _hostname(value: str) -> str:
    value = value.strip().lower()
    if value.startswith("["):  # IPv6 entre corchetes
        return value.split("]")[0] + "]"
    return value.rsplit(":", 1)[0] if value.count(":") == 1 else value


@app.middleware("http")
async def security_middleware(request: Request, call_next):
    # Tanto el Host como el X-Forwarded-Host (que pone el frontend con el nombre real que
    # usó el navegador) deben ser nombres permitidos.
    allowed = get_settings().allowed_host_set()
    for header in ("host", "x-forwarded-host"):
        value = request.headers.get(header)
        if value is not None and _hostname(value) not in allowed:
            return JSONResponse({"detail": "Nombre de servidor no permitido"}, status_code=400)
    # Las peticiones que cambian datos deben llevar una cabecera propia. Un navegador no
    # puede enviarla desde otra web sin permiso (CORS no está habilitado), lo que bloquea
    # ataques de falsificación de peticiones (CSRF).
    if request.method in UNSAFE_METHODS and request.headers.get(CSRF_HEADER) != "1":
        return JSONResponse({"detail": "Falta la cabecera de seguridad"}, status_code=403)
    response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Referrer-Policy"] = "no-referrer"
    response.headers["Cache-Control"] = "no-store"
    return response


@app.get("/api/health")
def health(db: Session = Depends(get_db)) -> JSONResponse:
    try:
        db.execute(text("SELECT 1"))
        database = "ok"
    except Exception:
        database = "error"
    ok = database == "ok"
    return JSONResponse(
        {"status": "ok" if ok else "degraded", "database": database, "version": app.version},
        status_code=200 if ok else 503,
    )


app.include_router(auth_router)
app.include_router(ai_router)
