# Estado de las funciones

Cada función está en uno de estos estados, y nunca se declara en uno superior al real:

| Estado | Significado |
| --- | --- |
| Diseñado | Descrito en el documento de diseño, sin código |
| Implementado | Código escrito y ejecutable |
| Probado | Pruebas automáticas superadas |
| Validado | Comprobado con datos o servicios reales durante un periodo definido |

Última actualización: 13-oct-2026, hito H1.

## Hito H1: esqueleto

| Función | Estado | Notas |
| --- | --- | --- |
| Arranque con un comando (Docker Compose) | Implementado | Los ficheros de Docker no se han podido ejecutar en el entorno de desarrollo (sin acceso a Docker Hub). La prueba automática de GitHub los construye y arranca en cada cambio |
| Base de datos y migraciones | Probado | Probado con PostgreSQL 16 en desarrollo. Con PostgreSQL 17 + TimescaleDB (la versión de Docker) se probará en la primera ejecución de GitHub. Las migraciones se prueban en cada ejecución |
| Acceso con contraseña y doble factor | Probado | Argon2id; código TOTP de un solo uso, también con accesos simultáneos; bloqueo tras 5 fallos en 15 minutos; sesiones de 12 horas |
| Protección frente a peticiones falsificadas (CSRF) y DNS rebinding | Probado | Cookie SameSite=Strict, cabecera propia obligatoria, lista de nombres de servidor permitidos y política de contenido (CSP) |
| Pasarela de IA: Anthropic | Probado con respuestas simuladas | Falta la prueba con tu clave real (botón "Probar conexión") |
| Pasarela de IA: OpenAI | Probado con respuestas simuladas | Falta la prueba con tu clave real. Ver "Limitaciones" sobre los nombres de modelos |
| Topes de gasto diario, mensual y por proveedor | Probado | Incluida la prueba de 8 llamadas simultáneas con presupuesto para una sola. Si un proveedor no responde a tiempo, se cuenta el coste máximo |
| Registro de cada llamada con su coste | Probado | |
| Caché de respuestas idénticas | Probado | 24 horas por defecto |
| Envoltorio de contenido externo no confiable | Probado | Se usará desde H4 |
| Fronteras entre módulos | Probado | `lint-imports` comprueba 4 reglas en cada cambio |
| Panel de costes y prueba de conexión | Implementado | Revisado visualmente en escritorio, móvil y modo oscuro |

## Criterios de aceptación de H1

- [ ] La aplicación arranca con un comando en tu ordenador.
- [ ] Una llamada de prueba a cada proveedor queda registrada con su coste.
- [x] Al superar el tope, las llamadas se bloquean (comprobado en pruebas automáticas).

Los dos primeros se marcarán cuando los compruebes en tu ordenador con tus claves.

## Limitaciones conocidas

- **Nombres de modelos de OpenAI.** Las dos páginas oficiales de OpenAI no coinciden: la
  de precios generales habla de "GPT-5.6 Sol/Terra/Luna" y la de desarrolladores de
  `gpt-6.1-sol` y `gpt-6-luna`. Se usan los de la página de desarrolladores. Si la prueba
  de conexión responde que el modelo no existe, hay que añadir el nombre correcto con su
  precio al catálogo (`pricing.py`): un modelo que no esté en el catálogo no se puede usar.
- **Reserva de presupuesto por exceso.** Antes de cada llamada se reserva el coste máximo
  posible contando un token por byte de texto, unas cuatro veces más de lo real en
  español. Cerca del tope, una petición larga puede bloquearse aunque en realidad cupiera.
- **Sin reintentos automáticos.** Si un proveedor falla, la llamada no se repite sola;
  quien la pidió decide si reintentar, con una reserva nueva.
- **Precios.** Comprobados el 13-oct-2026. Un modelo sin precio en el catálogo no se puede
  llamar, para que el control de gasto nunca quede a ciegas.
- **Bloqueo de acceso.** Cinco intentos fallidos bloquean el correo 15 minutos, también si
  los hace otra persona. Los intentos durante el bloqueo no lo alargan. Se puede
  desbloquear antes con la orden `unlock-user`.
- **Mes de facturación.** Los topes usan el mes natural en hora UTC (en España, el mes
  "cambia" a la 1:00 o 2:00 del día 1).
- **Redis y tareas programadas** se incorporan en H2, cuando haga falta la ingesta diaria.
