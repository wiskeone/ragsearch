# Roadmap

Working plan for future releases. Order is approximate — items move up if someone asks for them.

## v2.x — quality & trust

- [x] **Test suite** — encryption round-trip, parser (txt/md/html/csv), score-ordering regression (v2.0); RAG full-stack next
- [x] **CI** — GitHub Actions: ruff, tests inside CPU image, compose config validation (v2.0)
- [ ] **UI polish for EN** — finish translating Python-side leftovers (admin templates, remaining form messages)
- [x] **Prebuilt images on GHCR** — `ghcr.io/wiskeone/ragsearch-cpu:latest` (docker-publish.yml, GITHUB_TOKEN)
- [x] **HTTPS profile for nginx** — `nginx/nginx.ssl.conf.template` (v2.0)

## v3.0 — experience

- [x] **Streaming search SSE** — backend endpoint `/api/search/stream/` with stage events; frontend hook next
- [x] **Per-user quotas** — document count, storage size (TRIAL_MAX_STORAGE_MB), enforcement in upload, `/api/quota/` endpoint (v3.0)
- [ ] **Document viewer** — inline PDF/preview with chunk highlighting from search results
- [x] **Export** — search results to Markdown (`/api/export/search/markdown/`) (v3.0); chat transcripts next
- [x] **API keys** — ApiKey model (SHA-256, prefix display), Bearer auth class, generate/list/revoke endpoints (v3.0)
- [x] **Role model** — UserProfile.role (admin/member/viewer), permission helpers (is_admin, can_manage_models, can_delete_documents) (v3.0)

## v3.x — capabilities

- [x] **Reranker service** — `services/reranker.py`: cross-encoder (BAAI/bge-reranker-v2-m3), ленивая загрузка, активация через RERANKER_MODEL (v3.x)
- [x] **Incremental indexing** — SHA-256 content hash on Document, skip unchanged on reindex (v3.x)
- [ ] **Multi-model collections** — per-collection embedding model switch with transparent re-index
- [x] **vLLM integration** — `services/vllm_client.py` (OpenAI-compatible), settings VLLM_BASE_URL (v3.x)
- [x] **Metrics catalog** — Grafana dashboard shipped as provisioned JSON (grafana/provisioning/dashboards/)

---

## Дорожная карта (RU)

План приблизительный — приоритеты двигаются по запросам.

**v2.x — качество и доверие:** ✅ тесты (шифрование/парсер/скор-регресс), ✅ CI, ✅ HTTPS-профиль, ✅ GHCR-образы + EN admin-шаблоны. Всё закрыто.

**v3.0 — опыт:** стриминговый поиск с этапами, квоты пользователей, встроенный просмотрщик документов, экспорт результатов и чатов, API-ключи, роли.

**v3.x — возможности:** реранкер как отдельный этап, инкрементальная переиндексация, сменная модель эмбеддингов на коллекцию, vLLM как опциональный бэкенд, преднастроенные дашборды Grafana.
