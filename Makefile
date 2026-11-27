# AEGIS — atajos de desarrollo
#
# El backend usa un entorno virtual propio (.venv): en sistemas con Python
# "gestionado por el sistema" (PEP 668) `pip install` global falla, y el README
# ya no lo pide.
VENV ?= .venv
PY   ?= $(VENV)/bin/python

.PHONY: install geo backend frontend build dev smoke browserless check clean

install:            ## dependencias de backend (en .venv) y frontend
	python3 -m venv $(VENV)
	$(VENV)/bin/pip install -r backend/requirements.txt -r backend/requirements-dev.txt
	cd frontend && npm ci

geo:                ## red viaria y ferrocarril (si no vienen en el repo)
	$(PY) scripts/fetch_geo.py

backend:            ## API + mapa en http://localhost:8000
	cd backend && ../$(PY) -m uvicorn app.main:app --host 0.0.0.0 --port 8000

frontend:           ## modo desarrollo del frontend en http://localhost:3001
	cd frontend && npm run dev

build:              ## export estático → frontend/site (lo sirve el backend)
	cd frontend && npm run build

dev:                ## backend + frontend de desarrollo a la vez
	bash scripts/dev.sh

smoke:              ## comprobaciones contra un servidor en marcha
	$(PY) scripts/smoke.py

browserless:        ## navegador remoto de Browserless (BROWSERLESS_TOKEN en .env)
	$(PY) scripts/check_browserless.py

check:              ## lo mismo que el CI: tipos, lint y tests (sin red)
	cd frontend && ./node_modules/.bin/tsc --noEmit
	cd frontend && npm run lint
	$(PY) -m pytest backend/tests -q

clean:
	rm -rf frontend/.next frontend/out frontend/site
	find . -name __pycache__ -type d -prune -exec rm -rf {} +
