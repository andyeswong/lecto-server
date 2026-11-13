# Lecto — cómo levantar el servidor

Servidor de biblioteca de manga en un contenedor. Sirve el catalogo, las paginas,
los thumbnails, colecciones, favoritos y la caja fuerte (vault). Auth opcional por
token (Bearer o cookie de sesion).

## Requisitos

- Podman (rootless) o Docker
- `podman-compose` o `docker compose`
- Tu biblioteca: carpetas con `<serie>/info.json` + `<serie>/Capitulo #N.cbz|cbr`

## 3 comandos (podman)

```bash
# 1. Construir la imagen
podman-compose build

# 2. Arrancar el servidor (http://localhost:8790)
LECTO_LIBRARY=/ruta/a/tu/biblioteca podman-compose up -d server

# 3. Importar la biblioteca (one-shot)
LECTO_LIBRARY=/ruta/a/tu/biblioteca podman-compose run --rm ingest
```

## 3 comandos (docker)

```bash
docker compose build
LECTO_LIBRARY=/ruta/a/tu/biblioteca docker compose up -d server
LECTO_LIBRARY=/ruta/a/tu/biblioteca docker compose run --rm ingest
```

> En Docker, `userns: keep-id` se ignora (Docker no lo soporta). Si usas Docker
> Desktop, quita `userns: keep-id` del compose.

> Usa rutas absolutas en `LECTO_LIBRARY`.

## Variables de entorno

| Variable | Default | Descripcion |
|---|---|---|
| `LECTO_LIBRARY` | `./library` | Ruta a tu biblioteca (series con info.json + cbz/cbr) |
| `LECTO_STORE` | `/data/store` | Store interno (store.db, pages/, thumbs/) |
| `LECTO_PORT` | `8790` | Puerto del servidor |
| `LECTO_TOKEN` | (off) | Si se pone, todo /api/* exige `Authorization: Bearer <token>` |
| `LECTO_CORS` | `*` | Valor de `Access-Control-Allow-Origin` |
| `LECTO_BODY_MAX` | `16384` | Tope de body en bytes |
| `LECTO_LOG` | (off) | Set a `1` para loguear cada peticion |

## Auth

Sin `LECTO_TOKEN`, el servidor es abierto. Con token:
- `/api/info` es público (handshake: dice si hay auth y si la sesión es válida).
- `/api/session` (POST `{token}`): valida el token y setea cookie `lecto_session`
  (HttpOnly, sha256 del token) para que los `<img src>` del cliente web funcionen.
- `/api/session` (DELETE): borra la cookie.
- Todo lo demás bajo `/api/*` exige el token por `Authorization: Bearer <token>`
  o por la cookie de sesión.

## Volúmenes

| Volumen | Tipo | Permisos | Contenido |
|---|---|---|---|
| library | bind mount | ro | tus series: `<serie>/info.json` + `<serie>/*.cbz\|cbr` |
| store | named volume | rw | store.db, pages/, thumbs/ (derivado, se regenera) |

## Notas

- **SELinux (Fedora/RHEL):** los bind mounts llevan `:Z` en el compose.
- **rootless podman:** `userns: keep-id` mapea tu uid del host al del contenedor.
- **CBR (RAR):** el contenedor incluye `bsdtar` (libarchive). CBZ (zip) siempre funciona.
- **Library read-only:** si una serie no tiene `info.json`, ingest intenta crearlo
  y falla en un montaje de solo lectura. Crea el `info.json` antes, o monta rw.
- **Healthcheck:** el Containerfile incluye HEALTHCHECK contra `/api/info` (público).
  Podman en formato OCI lo ignora; el compose lo lleva en runtime.

## CI

- `.github/workflows/ci.yml`: dos jobs al push/PR — (a) pruebas del servidor
  (`python3 -m unittest discover -s tests -t .`) y (b) build de la imagen + smoke test.
- `.github/workflows/release.yml`: publica la imagen en GHCR al crear un tag `v*`.
