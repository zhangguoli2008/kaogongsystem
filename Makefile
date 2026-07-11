.PHONY: dev down migrate preflight seed smoke test

preflight:
	bash scripts/dev-preflight.sh

dev: preflight
	docker compose up --build

down:
	docker compose down

migrate:
	docker compose exec api alembic upgrade head

seed:
	docker compose exec api python -m app.seed

smoke:
	bash scripts/smoke.sh

test:
	cd apps/api && uv run pytest -q
	cd apps/web && npm test -- --run
	cd apps/web && npm run lint
	cd apps/web && npm run build
