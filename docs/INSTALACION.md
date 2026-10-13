# Instalación en tu ordenador

Guía para poner en marcha Investool sin conocimientos de programación. Tiempo estimado:
30 minutos la primera vez.

## Antes de empezar

Debes tener hechos los pasos 1 a 6 de la guía de preparación del documento de diseño:

- Bitwarden (gestor de contraseñas).
- Cuenta de GitHub con acceso al repositorio `Investool`.
- Git instalado.
- Docker Desktop instalado y abierto (debe indicar "Engine running").
- Claves de API de Anthropic y OpenAI guardadas en Bitwarden, con sus límites de gasto.
- Una app de autenticación en el móvil (Bitwarden Authenticator, Google Authenticator o
  Microsoft Authenticator).

## 1. Descargar el código

La forma más sencilla es con **GitHub Desktop** (gratuito, desde desktop.github.com):
inicia sesión con tu cuenta, elige clonar un repositorio y selecciona `Investool`. Anota la
carpeta donde lo guarda.

Si prefieres la terminal:

```bash
git clone https://github.com/diegoembid/Investool.git
cd Investool
```

## 2. Abrir una terminal en la carpeta del proyecto

**Windows 11** (la forma más fiable):

1. Abre la carpeta `Investool` en el Explorador de archivos. Dentro deben verse las
   carpetas `backend`, `frontend` y `docs`.
2. Haz clic en la barra de dirección de arriba (donde aparece la ruta de la carpeta), de
   modo que el texto quede seleccionado.
3. Escribe `powershell` y pulsa Intro. Se abre una ventana azul o negra que ya está en esa
   carpeta.

Otras formas en Windows: con la carpeta abierta, clic derecho en un espacio vacío (no
encima de un archivo) y "Abrir en Terminal", que a veces está dentro de "Mostrar más
opciones". O, en GitHub Desktop, el menú "Repository" y la opción de abrir en la línea de
órdenes.

**Mac:** abre la app Terminal, escribe `cd ` (con un espacio), arrastra la carpeta
`Investool` a la ventana y pulsa Intro.

**Comprobación:** escribe `dir` (Windows) o `ls` (Mac) y pulsa Intro. En la lista debe
aparecer `docker-compose.yml`. Si no aparece, estás en otra carpeta: a veces GitHub
Desktop crea una carpeta `Investool` dentro de otra; entra en la que contiene
`docker-compose.yml` y repite.

Todas las órdenes siguientes se escriben (o se pegan) en esa ventana y se ejecutan
pulsando Intro. Copia solo el texto de la orden, sin las comillas invertidas que la
rodean en esta guía. Para pegar en PowerShell, clic derecho dentro de la ventana o
Ctrl+V.

## 3. Crear el fichero de configuración

Copia la plantilla:

- Windows: `copy .env.example .env`
- Mac: `cp .env.example .env`

Si todo va bien, no aparece ningún mensaje. Para comprobarlo, escribe `dir` (Windows) o
`ls -a` (Mac): debe aparecer `.env` en la lista.

Genera la clave maestra y la contraseña de la base de datos:

```bash
docker compose run --rm --no-deps backend python -m app.cli generate-secret
```

La primera vez tarda unos minutos porque Docker descarga y prepara el backend. Al final
aparecen dos líneas, `APP_SECRET_KEY=...` y `POSTGRES_PASSWORD=...`.

Abre el fichero `.env` para editarlo:

- Windows: `notepad .env`
- Mac: `open -e .env`

Y haz estos cambios:

1. Sustituye las líneas `APP_SECRET_KEY=CAMBIAR...` y `POSTGRES_PASSWORD=CAMBIAR...` por
   las dos que has generado.
2. Pega tus claves en `ANTHROPIC_API_KEY=` y `OPENAI_API_KEY=` (copiándolas desde
   Bitwarden, sin espacios ni comillas).
3. Guarda y cierra.

Guarda también `APP_SECRET_KEY` y `POSTGRES_PASSWORD` en Bitwarden. El fichero `.env`
nunca se sube a GitHub.

## 4. Arrancar la aplicación

```bash
docker compose up -d --build
```

La primera vez tarda entre 5 y 10 minutos. Para comprobar que todo está en marcha:

```bash
docker compose ps
```

Los tres servicios (`db`, `backend` y `frontend`) deben aparecer como "running", y
`db` y `backend` además como "healthy".

## 5. Crear tu usuario con doble factor

```bash
docker compose exec backend python -m app.cli create-user
```

1. Escribe tu correo y una contraseña de al menos 12 caracteres (no se ve al escribirla;
   es normal). Guárdala en Bitwarden.
2. Aparece un código QR en la terminal. Escanéalo con la app de autenticación del móvil.
   Si no se lee bien, agranda la ventana o introduce a mano la clave que aparece debajo.
3. Guarda también esa clave en Bitwarden: permite recuperar el doble factor si pierdes el
   móvil.
4. Escribe el código de 6 dígitos que muestra la app. Si es correcto, el usuario queda
   creado.

## 6. Entrar y probar los proveedores de IA

1. Abre http://localhost:3000 en el navegador.
2. Entra con tu correo, tu contraseña y el código de la app.
3. En el panel, pulsa **Probar conexión** en Anthropic y en OpenAI. Cada prueba cuesta
   menos de una milésima de dólar y queda registrada en "Últimas llamadas".

Si las dos pruebas funcionan, el hito H1 está comprobado en tu ordenador. Si alguna falla,
el mensaje dice el motivo (clave incorrecta, modelo inexistente, tope alcanzado...).

## Uso diario

| Quiero... | Orden |
| --- | --- |
| Parar la aplicación | `docker compose stop` |
| Volver a arrancarla | `docker compose start` |
| Ver el gasto de IA en la terminal | `docker compose exec backend python -m app.cli ai-usage` |
| Probar los proveedores desde la terminal | `docker compose exec backend python -m app.cli ai-smoke-test` |
| Cambiar contraseña o doble factor | `docker compose exec backend python -m app.cli reset-user` |
| Desbloquear el acceso tras varios intentos fallidos | `docker compose exec backend python -m app.cli unlock-user` |
| Ejecutar las pruebas automáticas | `docker compose exec backend pytest` |
| Ver los registros si algo falla | `docker compose logs --tail 100 backend` |

## Actualizar a una versión nueva

Cuando haya cambios nuevos en GitHub:

1. En GitHub Desktop, pulsa el botón para traer cambios (o en la terminal: `git pull`).
2. Reconstruye y reinicia: `docker compose up -d --build`.

Las migraciones de la base de datos se aplican solas al arrancar el backend. Tus datos se
conservan.

## Problemas frecuentes

| Síntoma | Causa probable y solución |
| --- | --- |
| `Falta POSTGRES_PASSWORD en el fichero .env` | No existe el fichero `.env` o falta esa línea. Repite el paso 3 |
| `APP_SECRET_KEY no está configurada` | Sigue la línea con `CAMBIAR`. Repite el paso 3 |
| `Cannot connect to the Docker daemon` | Docker Desktop no está abierto. Ábrelo y espera a "Engine running" |
| `port is already allocated` | Otro programa usa el puerto 3000 u 8000. Ciérralo o reinicia el ordenador |
| "Correo, contraseña o código incorrectos" con datos correctos | La hora del ordenador o del móvil no está bien. Activa la hora automática en ambos |
| "Demasiados intentos fallidos" | Espera 15 minutos desde el último fallo, o desbloquea con `unlock-user` (tabla anterior) |
| La prueba de OpenAI dice que el modelo no existe | OpenAI ha cambiado el nombre del modelo. Avísame: hay que añadir el nombre nuevo y su precio al catálogo. Cambiarlo solo en `.env` no basta |

## Importante sobre `POSTGRES_PASSWORD`

La contraseña de la base de datos se fija la primera vez que arranca. Si la cambias después
en `.env`, el backend no podrá conectarse. Para empezar de cero (borra todos los datos):
`docker compose down -v` y vuelve al paso 4.
