# Lecto server — imagen del servidor para el repo público.
# Solo el servidor (sin la app). Python 3 + Pillow + bsdtar (CBR).
FROM python:3.12-slim

# bsdtar (libarchive-tools) para extraer CBR. Pillow como rueda (incluye libjpeg, zlib).
RUN apt-get update \
    && apt-get install -y --no-install-recommends libarchive-tools \
    && rm -rf /var/lib/apt/lists/* \
    && pip install --no-cache-dir Pillow

# Usuario no root.
RUN groupadd -r lecto && useradd -r -g lecto -u 1000 -d /app -s /sbin/nologin lecto

WORKDIR /app

# Todos los módulos del servidor.
COPY --chown=lecto:lecto *.py ./

# Volúmenes: library (ro), store (rw). El build web (LECTO_WEB) es opcional:
# el servidor funciona sin él (solo /api/*); si lo montas, sirve el cliente web.
RUN mkdir -p /data/library /data/store && chown -R lecto:lecto /data

USER lecto

ENV LECTO_PORT=8790 \
    LECTO_STORE=/data/store \
    LECTO_LIBRARY=/data/library

EXPOSE 8790

# Salud: /api/info es público (handshake), no necesita token.
HEALTHCHECK --interval=30s --timeout=5s --retries=3 --start-period=10s \
    CMD python3 -c "import os,urllib.request; urllib.request.urlopen(f'http://localhost:{os.environ.get(\"LECTO_PORT\",\"8790\")}/api/info').read()" || exit 1

CMD ["python3", "server.py"]
