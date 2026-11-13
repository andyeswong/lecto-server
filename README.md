# Lecto — servidor de biblioteca

Servidor de biblioteca para Lecto, un lector de manga, cómic y ebook pensado para
tablet. Sirve el catálogo, las páginas originales, las miniaturas generadas bajo
demanda, colecciones, favoritos y una caja fuerte opcional. No usa frameworks:
stdlib de Python + Pillow.

La app cliente (Lecto) es cerrada y es aparte; este servidor es el que
cualquiera puede instalar en su casa para servir su propia biblioteca a la app.
Más sobre la app: <https://lecto.andres-wong.com>.

## Qué es

- Un índice SQLite (`store.db`) de series, capítulos y páginas.
- Originales en disco (`pages/<serie>/<capítulo>/NNN.jpg`), normalizados a 1400 px de ancho.
- Miniaturas WebP en 3 tamaños (`s` 120, `m` 280, `l` 560), generadas bajo
  demanda y cacheadas en disco.
- Una API JSON para la app cliente.
- Colecciones (grupos de series) y favoritos (series, páginas o recortes).
- Una caja fuerte opcional: series ocultas del catálogo detrás de un PIN.

## Instalación

Requisitos: Python 3.10+ y [Pillow](https://python-pillow.org). Para ingerir
`.cbr` hace falta `bsdtar` (libarchive), disponible en la mayoría de distros.

```bash
pip install -r requirements.txt     # solo Pillow
```

## Arranque

```bash
# desde la carpeta del servidor
python3 server.py

# o, equivalente, vía __main__.py
python3 .
```

Variables de entorno (ninguna ruta está hardcodeada):

| Variable | Default | Qué hace |
|---|---|---|
| `LECTO_STORE` | `./store` | índice + originales + cache de thumbs |
| `LECTO_WEB` | `./web` | build web de la app (opcional; sin él, solo API) |
| `LECTO_PORT` | `8790` | puerto |
| `LECTO_LIBRARY` | `./library` | carpeta a ingerir (referencia) |
| `LECTO_TOKEN` | _(vacío)_ | si se pone, `/api/*` exige `Authorization: Bearer <token>` o cookie de sesión |
| `LECTO_CORS` | `*` | valor de `Access-Control-Allow-Origin` |
| `LECTO_BODY_MAX` | `16384` | tope de body en bytes |
| `LECTO_LOG` | _(vacío)_ | si vale `1`, loguea cada petición |

## Ingesta de la biblioteca

```bash
python3 ingest.py ./library
python3 ingest.py ./library --force   # reimportar
```

La biblioteca es un directorio de carpetas de series:

```
library/
  Little Nemo/                         una carpeta por serie
    info.json                      metadatos (ver abajo)
    Capitulo 1 Nombre_a1b2c3.cbz
    Capitulo 2 Nombre_d4e5f6.cbz
  Hokusai Manga/
    ...
```

La ingesta es incremental: un capítulo cuyo archivo fuente (nombre + tamaño) ya
está indexado se salta. Cada capítulo se escribe en un dir temporal y se renombra
en sitio, así un crash nunca deja un capítulo a medias visible para el servidor.

CBZ es un zip de imágenes. CBR necesita `bsdtar` (libarchive).

### Nombres de capítulo

`ingest.py` reconoce el número de capítulo de los formatos comunes: `Capítulo 12.5`,
`Chapter 12.5`, `Ch.12`, `#12`, `Vol. 01 c003`, `Tomo 3`. Si dos archivos dan el
mismo id de capítulo, se desambiguan con un sufijo `_2` y se avisa por log; nunca
se pisan.

### Biblioteca de solo lectura

Si la carpeta de la serie no se puede escribir (biblioteca montada `:ro`),
`info.json` y los overrides de lectura se guardan en un overlay en el store
(`<store>/info/<id>.json`). El formato canónico sigue siendo `info.json` en la
carpeta; el overlay es solo el respaldo cuando no hay permiso de escritura.

## Formato de `info.json`

Metadatos por serie, formato propio (al estilo de Mihon; no ComicInfo.xml).
Si la carpeta no tiene `info.json`, se crea a partir de lo que encuentre
(ComicInfo.xml del tope o dentro del primer CBZ, un `details.json` heredado,
o el nombre de la carpeta).

```json
{
  "schema": 1,
  "id": "little-nemo",
  "title": "Little Nemo in Slumberland",
  "author": "Winsor McCay",
  "artist": "Winsor McCay",
  "description": "",
  "genres": ["Aventura"],
  "status": "ongoing",
  "kind": "manga",
  "language": "es",
  "source": "server",
  "cover": {"chapter": "c1", "page": 3},
  "reading": {"direction": "rtl"}
}
```

- `id`: slug estable, `[a-z0-9_-]`, se usa en las URLs.
- `kind`: etiqueta (`manga | manhwa | manhua | comic | ebook | other`). La
  dirección de lectura **no** se infiere del tipo.
- `source`: `device` o `server`.
- `cover`: opcional; si falta, se usa la página 1 del primer capítulo.
- `reading`: **solo overrides** de lo que el usuario cambió. Lo que no está cae
  al default global. Un valor `null` quita el override.

### Ajustes de lectura

| Campo | Valores | Default |
|---|---|---|
| `direction` | `ltr`, `rtl` | `ltr` |
| `layout` | `auto`, `single`, `double`, `scroll` | `auto` |
| `fit` | `screen`, `width` | `screen` |
| `coverAlone` | `true`, `false` | `true` |
| `background` | `black`, `gray`, `white` | `black` |

## API

| Método | Ruta | Descripción |
|---|---|---|
| GET | `/api/info` | handshake público: server, api version, auth required |
| GET | `/api/catalog` | series, capítulos, dimensiones de página (sin las de la caja fuerte) |
| GET | `/api/pages/<serie>/<cap>/<n>.jpg` | página original |
| GET | `/api/pages/<serie>/<cap>/<n>.png` | página como PNG (descarga) |
| GET | `/api/thumbs/<s\|m\|l>/<serie>/<cap>/<n>.webp` | miniatura (render on-demand) |
| GET | `/api/stats` | store, cache de thumbs, warmer |
| GET | `/api/settings` | defaults de lectura + valores permitidos |
| PUT | `/api/settings/reading` | cambiar defaults (`null` = factory) |
| PUT | `/api/series/<serie>/reading` | override por serie (`null` = quitar) |
| DELETE | `/api/series/<serie>/chapters/<cap>` | borrar un capítulo (su archivo también) |
| GET | `/api/collections` | `[{id, name, series:[ids]}]` en orden |
| POST | `/api/collections` | `{name, series?}` → nueva colección |
| PUT | `/api/collections/<id>` | `{name?, series?, position?}` |
| DELETE | `/api/collections/<id>` | borrar |
| GET | `/api/favs` | favoritos (series, páginas, recortes) |
| POST | `/api/favs` | `{kind, series, chapter?, page?, rect?}` → nuevo o existente |
| DELETE | `/api/favs/<id>` | borrar favorito |
| GET | `/api/favs/<id>.webp` | recorte como imagen |
| GET | `/api/favs/<id>.png` | recorte como descarga |
| GET | `/api/vault` | estado de la caja fuerte |
| POST | `/api/vault/create` | `{pin}` — crear el PIN (4-6 dígitos) |
| POST | `/api/vault/open` | `{pin}` — series de la caja fuerte (403 PIN malo, 429 demasiados intentos) |
| POST | `/api/vault/add` | `{series:[ids]}` — ocultar series (sin PIN) |
| POST | `/api/vault/remove` | `{pin, series}` — devolver al catálogo |
| POST | `/api/vault/reset` | olvidé el PIN: vacía la caja, las series vuelven |
| POST | `/api/session` | `{token}` → cookie HttpOnly (login web) |
| DELETE | `/api/session` | borrar cookie |
| POST | `/api/thumbs/warm` | renderizar thumbs faltantes en background |

## Seguridad

Lecto está pensado para una **red local de confianza**. Quien lo exponga en
su red debe saber qué tiene y qué no:

- **Sin autenticación por defecto.** Cualquiera en la red puede leer el catálogo
  y las páginas. Si quieres protegerlo, define `LECTO_TOKEN`: a partir de ese
  momento todo `/api/*` exige autenticación de una de dos formas:
  - **Header** `Authorization: Bearer <token>` (cliente nativo).
  - **Cookie** de sesión: `POST /api/session {token}` valida el token y setea
    una cookie `lecto_session` HttpOnly + SameSite=Strict. `DELETE /api/session`
    la borra. Esto es para el cliente web, donde los `<img src>` no pueden mandar
    headers. El valor de la cookie es `sha256(token)` (no el token en claro).
  El endpoint `/api/info` es público (handshake); el preflight CORS (OPTIONS)
  no exige auth.
- **CORS en `*`.** Cambialo con `LECTO_CORS` al origen exacto de la app.
- **HTTP en claro.** No hay TLS. En una LAN va bien; si lo expones más allá,
  ponle un proxy con HTTPS delante.
- **Tope de body 16 KB** (`LECTO_BODY_MAX`).
- **Path traversal:** las rutas de API usan regex con whitelist; los estáticos
  validan `realpath` contra `LECTO_WEB`.
- **Caja fuerte:** es **privacidad en la app, no control de acceso**. El catálogo
  no lista las series de la caja fuerte, pero sus páginas y miniaturas siguen
  siendo servidas a quien tenga el token del servidor y conozca los ids. El PIN
  se guarda hasheado (sha256 con salt); los intentos fallidos se limitan (5
  seguidos → 30s de bloqueo).
- **Compresión gzip:** las respuestas de texto (HTML, CSS, JS, JSON) se
  comprimen con gzip cuando el cliente lo acepta y el cuerpo ≥ 1 KB. Las imágenes
  no se comprimen (ya lo están).

## Pruebas

```bash
python3 -m unittest discover -s tests
```

Las pruebas usan una **biblioteca sintética** generada por código
(`tests/fixtures.py`): CBZ y CBR con páginas hechas en Pillow, un `info.json`
por serie y una portada ancha para doble página. El servidor arranca en un
puerto efímero con `LECTO_STORE` apuntando a un tmpdir.

## Contenedor

Incluye `Containerfile` y `compose.yaml`. Ver
`compose.yaml` para el uso con podman-compose.

```bash
podman-compose build
podman-compose up -d server            # arranca el servidor
podman-compose run --rm ingest          # importa la biblioteca
```

## Licencia

MIT — ver [LICENSE](LICENSE).
