"""Funciones de analista: graduación, patrones, casos, grafo y productos.

Se mantienen aparte del núcleo (`api/routes.py`, `storage/sqlite.py`) para que
el motor de mapas siga siendo legible: aquí vive la capa de *inteligencia*, con
su propio almacén auxiliar (mismo fichero SQLite, tablas propias).
"""
