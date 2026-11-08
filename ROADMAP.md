# Roadmap

Working plan for future releases. Order is approximate — items move up if someone asks for them.

## v2.x — quality & trust

- [ ] **Test suite** — pytest coverage for RAG services (chunking, hybrid merge), encryption round-trip, API auth matrix
- [ ] **CI** — GitHub Actions: lint (ruff), `python manage.py check`, template parse validation, docker build (CPU image)
- [ ] **UI polish for EN** — finish translating Python-side leftovers (admin templates, remaining form messages)
- [ ] **Prebuilt images on Docker Hub / GHCR** — `docker compose pull` instead of building locally
- [ ] **HTTPS profile for nginx** — ready-made TLS config + Let's Encrypt instructions

## v3.0 — experience

- [ ] **Streaming search UI** — show retrieval progress per stage (parse → embed → FAISS → BM25 → merge)
- [ ] **Per-user quotas** — document count, storage size, LLM tokens (trial system is already partially wired)
- [ ] **Document viewer** — inline PDF/preview with chunk highlighting from search results
- [ ] **Export** — search results and chat transcripts to Markdown/CSV
- [ ] **API keys** — token auth for programmatic access to `/api/`
- [ ] **Role model** — admin / member separation beyond Django staff flag

## v3.x — capabilities

- [ ] **Reranker service** — cross-encoder reranking as an optional Celery stage
- [ ] **Incremental indexing** — re-embed only changed documents
- [ ] **Multi-model collections** — per-collection embedding model switch with transparent re-index
- [ ] **vLLM integration** — optional inference backend (OpenAI-compatible) alongside transformers
- [ ] **Metrics catalog** — Grafana dashboards shipped as provisioned JSON

---

## Дорожная карта (RU)

План приблизительный — приоритеты двигаются по запросам.

**v2.x — качество и доверие:** тест-сьют (RAG-сервисы, шифрование, авторизация), CI (ruff + check + сборка CPU-образа), доводка EN-строк, готовые образы в GHCR, HTTPS-профиль nginx.

**v3.0 — опыт:** стриминговый поиск с этапами, квоты пользователей, встроенный просмотрщик документов, экспорт результатов и чатов, API-ключи, роли.

**v3.x — возможности:** реранкер как отдельный этап, инкрементальная переиндексация, сменная модель эмбеддингов на коллекцию, vLLM как опциональный бэкенд, преднастроенные дашборды Grafana.
