"""Punto de entrada para `python3 server/` o `python3 -m server`.

Anade el directorio del paquete a sys.path para que los imports planos
(import store, import thumbs...) resuelvan sin importar el cwd.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from server import main

if __name__ == '__main__':
    main()
