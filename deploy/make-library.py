"""Biblioteca sintetica para probar el contenedor de Lecto.

Genera <dir>/<series>/info.json + <series> #N.cbz con paginas hechas con Pillow.
Sin obras con derechos de autor: rectangulos de color con el numero de pagina.

    python3 make-library.py <dir>

Dos series, cinco capitulos, 26 paginas total.
"""
import io
import json
import os
import sys
import zipfile

from PIL import Image, ImageDraw


def make_page(n, total, w=800, h=1200):
    """Rectangulo de color con el numero de pagina."""
    r = int(128 + 127 * (n / max(total, 1))) % 256
    g = int(80 + 100 * ((n * 7) % 13) / 13) % 256
    b = int(200 - 150 * (n / max(total, 1))) % 256
    im = Image.new('RGB', (w, h), (r, g, b))
    d = ImageDraw.Draw(im)
    d.text((w // 2 - 40, h // 2), f"{n}/{total}", fill='white')
    return im


def make_cbz(path, n_pages):
    """CBZ = zip de JPEGs. ingest.py busca #N en el nombre para el numero."""
    with zipfile.ZipFile(path, 'w', zipfile.ZIP_STORED) as z:
        for i in range(1, n_pages + 1):
            buf = io.BytesIO()
            make_page(i, n_pages).save(buf, 'JPEG', quality=85)
            z.writestr(f"{i:03d}.jpg", buf.getvalue())


def make_series(lib_dir, sid, title, n_chapters=3, pages_per_chapter=6):
    folder = os.path.join(lib_dir, sid)
    os.makedirs(folder, exist_ok=True)
    # info.json pre-creado: la biblioteca es read-only en el contenedor,
    # e ingest.py lo escribe si falta (infofile.load). Lo dejamos para que
    # no intente escribir en un volumen de solo lectura.
    info = {
        "schema": 1,
        "id": sid,
        "title": title,
        "author": "Autor de Prueba",
        "artist": "Artista de Prueba",
        "description": f"Serie sintetica: {title}",
        "genres": ["Aventura", "Accion"],
        "status": "ongoing",
        "kind": "manga",
        "language": "es",
        "source": "server",
    }
    with open(os.path.join(folder, "info.json"), 'w', encoding='utf-8') as f:
        json.dump(info, f, ensure_ascii=False, indent=2)
        f.write('\n')
    for ch in range(1, n_chapters + 1):
        make_cbz(os.path.join(folder, f"{title} #{ch}.cbz"), pages_per_chapter)


def main():
    lib_dir = os.path.expanduser(sys.argv[1] if len(sys.argv) > 1 else '~/lecto-test-library')
    os.makedirs(lib_dir, exist_ok=True)
    make_series(lib_dir, "demo-saga", "Saga Demo", n_chapters=3, pages_per_chapter=6)
    make_series(lib_dir, "demo-rpg", "RPG Demo", n_chapters=2, pages_per_chapter=4)
    total_pages = 3 * 6 + 2 * 4
    print(f"Biblioteca sintetica en {lib_dir}")
    print(f"  2 series, 5 capitulos, {total_pages} paginas")


if __name__ == '__main__':
    main()
