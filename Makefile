# AEGIS — atajos de desarrollo
.PHONY: install geo backend frontend build dev smoke clean

install:            ## dependencias de backend y frontend
	pip install -r backend/requirements.txt
	cd frontend && npm install

geo:                ## red viaria y ferrocarril (si no vienen en el repo)
	python3 scripts/fetch_geo.py

backend:            ## API + mapa en http://localhost:8000
	cd backend && python3 -m uvicorn app.main:app --host 0.0.0.0 --port 8000

frontend:           ## modo desarrollo del frontend en http://localhost:3000
	cd frontend && npm run dev

build:              ## export estático → frontend/site (lo sirve el backend)
	cd frontend && npm run build

dev:                ## backend + frontend de desarrollo a la vez
	bash scripts/dev.sh

smoke:              ## 29 comprobaciones contra un servidor en marcha
	python3 scripts/smoke.py

clean:
	rm -rf frontend/.next frontend/out frontend/site
	find . -name __pycache__ -type d -prune -exec rm -rf {} +
