.PHONY: install test lint format up down logs health graph-init db-init

install:
	python -m pip install -e ".[dev]"

test:
	pytest -q

lint:
	ruff check .
	ruff format --check .

format:
	ruff check --fix .
	ruff format .

up:
	docker compose up --build -d

down:
	docker compose down

logs:
	docker compose logs -f api

health:
	curl -fsS http://localhost:8000/health/ready

graph-init:
	python -m decisiongraph.infrastructure.graph_bootstrap

db-init:
	python -m decisiongraph.infrastructure.database_bootstrap
