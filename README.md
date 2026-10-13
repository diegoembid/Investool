# Investool

Plataforma privada de inteligencia de inversiones: detecta oportunidades con evidencia
trazable, registra cada predicción y mide sus resultados frente a una referencia. Uso
personal; no es asesoramiento financiero.

El diseño completo (requisitos, arquitectura, proveedores, presupuesto, fases) está en el
documento "Plataforma de inteligencia de inversiones — Diseño inicial (Fase 0)".

## Estado

Hito actual: **H1, esqueleto**. Qué hay y qué falta, función a función:
[docs/ESTADO.md](docs/ESTADO.md).

## Empezar

- Instalación paso a paso, sin conocimientos de programación:
  [docs/INSTALACION.md](docs/INSTALACION.md)
- Cómo está organizado el código: [docs/ARQUITECTURA.md](docs/ARQUITECTURA.md)

Resumen para quien ya tenga Docker:

```bash
cp .env.example .env
docker compose run --rm --no-deps backend python -m app.cli generate-secret   # pegar en .env
docker compose up -d --build
docker compose exec backend python -m app.cli create-user
# Abrir http://localhost:3000
```

## Principio de diseño

El código calcula, las IAs interpretan. Ninguna cifra que se muestre procede de un modelo
de IA: precios, indicadores y métricas los calcula código probado sobre datos con fuente.
