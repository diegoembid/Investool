# Arquitectura

Monolito modular: un backend en Python (FastAPI) y un frontend en Next.js sobre PostgreSQL
con TimescaleDB, en contenedores Docker. El razonamiento completo y las alternativas
descartadas están en el documento de diseño (sección C).

## Estructura del repositorio

```
backend/
  app/
    core/            configuración, base de datos, cifrado
    modules/
      auth/          acceso: contraseña, doble factor, sesiones
      ai_gateway/    único punto de salida hacia proveedores de IA
      ingestion/     (H2) conectores de datos
      market_data/   (H2) series de precios point-in-time
      news/          (H4) noticias, fiabilidad, deduplicación
      quant/         (H3) indicadores y valoración, código puro
      agents/        (H5) roles del comité de IA
      opportunities/ (H5) fichas de oportunidad
      ledger/        (H6) registro sellado de predicciones
      portfolio/     (H6) cartera simulada y backtesting
      risk/          (Fase 4) límites operativos
      execution/     (Fase 4) conexión a bróker
    cli.py           órdenes de administración
  alembic/           migraciones de la base de datos
  tests/             pruebas automáticas
frontend/            interfaz web (Next.js)
docs/                manuales
```

## Reglas entre módulos

Se comprueban automáticamente con `lint-imports` (configuración en `backend/pyproject.toml`):

1. `quant` no puede usar red, IA ni conectores: solo calcula.
2. `agents` no puede tocar `risk`, `execution` ni `portfolio`.
3. Solo `ai_gateway` puede usar las librerías de Anthropic y OpenAI.
4. `risk` no depende de la IA.

## Pasarela de IA

Cada llamada sigue tres pasos, cada uno en su propia transacción:

1. **Reserva.** Se calcula el coste máximo posible (un token por byte de entrada, que
   nunca se queda corto, más el máximo de tokens de salida, con el precio de contexto
   largo si esa cota supera el umbral) y se compara con el tope diario global, el mensual global y
   el mensual del proveedor. Un bloqueo de la base de datos impide que dos llamadas
   simultáneas reserven el mismo presupuesto.
2. **Llamada** al proveedor.
3. **Cierre.** Se sustituye la reserva por el coste real que informa el proveedor.

Los SDK no reintentan solos: cada intento pasa por la pasarela con su propia reserva. Si
el proveedor no responde a tiempo o se corta la conexión, no se sabe si cobró, así que se
cuenta el coste máximo reservado. Una reserva que no se cierra en 30 minutos (por ejemplo,
por una caída) también se da por gastada con su importe máximo. Las llamadas bloqueadas
quedan registradas igualmente.

El catálogo de precios está en `backend/app/modules/ai_gateway/pricing.py`, con la fecha y
la página oficial de cada precio.

## Seguridad

- Puertos abiertos solo en `127.0.0.1`: nada es accesible desde la red local.
- Solo se aceptan los nombres de servidor de `ALLOWED_HOSTS` (protección frente a DNS
  rebinding) y el frontend envía una política de contenido (CSP) estricta.
- Los intentos de acceso de un mismo correo se procesan de uno en uno (bloqueo de la base
  de datos), así que ni el recuento de fallos ni el uso único del código TOTP se pueden
  saltar con peticiones simultáneas.
- Contraseña con Argon2id; semilla del doble factor cifrada con `APP_SECRET_KEY`.
- Cookie de sesión `HttpOnly` y `SameSite=Strict`; `Secure` en producción.
- Las peticiones que cambian datos exigen la cabecera `X-Investool-Request`.
- El navegador solo habla con el frontend, que reenvía `/api/*` al backend: no hace
  falta habilitar CORS.
- OpenAI se llama con `store=false` para que no guarde las conversaciones.
- Las pruebas nunca hacen llamadas reales: los adaptadores se prueban con transportes
  simulados y, por si acaso, las direcciones de los proveedores apuntan a un puerto cerrado.
