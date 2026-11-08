# RAG Search

Self-hosted **RAG (Retrieval-Augmented Generation) search & chat** with encrypted document storage, hybrid FAISS + BM25 retrieval, and a local LLM (Qwen 3.5-4B) — fully Dockerized, runs on a single GPU machine.

> **UI language:** Russian (English UI is planned).

## Features

- **Document collections** — upload PDF/DOCX/PPTX/EPUB/HTML/CSV/TXT; files are **encrypted at rest** (Fernet) and stored server-side
- **Hybrid retrieval** — FAISS dense vectors (BGE-M3) + BM25 keyword search, merged with normalized scoring
- **Local LLM chat** — Qwen 3.5-4B quantized via bitsandbytes 4-bit, streaming answers with source citations
- **Separate GPU/CPU workers** — Celery queues split heavy model work from light parsing
- **Hugging Face integration** — search/download models straight from the Hub
- **Monitoring** — Prometheus + Grafana dashboards, Flower for Celery, pgAdmin for Postgres

## Stack

| Layer | Tech |
|---|---|
| Backend | Django 5 + Django REST Framework, Gunicorn |
| Frontend | Django templates + Bootstrap 5 (dark theme) |
| Database | PostgreSQL 15 |
| Cache / queue | Redis 7 + Celery 5 (GPU & CPU workers, Flower) |
| AI | sentence-transformers (BGE-M3), FAISS, rank_bm25, transformers + bitsandbytes |
| Web | Nginx |
| Runtime | Docker + NVIDIA CUDA 12.8 (GPU) / CPU-only image included |

## Quick start

Requirements: Docker + `docker-compose`, NVIDIA GPU with the container toolkit (or use `Dockerfile.cpu` for CPU-only).

```bash
# 1. Configure environment
cp .env.example .env
#    then edit .env (SECRET_KEY, DB_PASSWORD, ENCRYPTION_KEY, ...)

# 2. Generate the document-encryption key and put it into .env as ENCRYPTION_KEY
./scripts/generate_encryption_key.sh

# 3. Build & run
docker-compose up -d

# 4. Create your admin user
docker exec -it rag_web python manage.py createsuperuser

# 5. Open the app
#    http://localhost
```

Stop: `docker-compose down`.

### Default service endpoints (after `up -d`)

| Service | URL |
|---|---|
| Web app | http://localhost |
| Swagger API docs | http://localhost/swagger/ |
| Flower (Celery monitor) | http://localhost:5555 |
| Grafana | http://localhost:3000 |
| pgAdmin | http://localhost:5050 |
| Prometheus | http://localhost:9090 |

> Change the default passwords in `docker-compose.yml` / `.env` before exposing anything beyond localhost.

## Configuration

All settings live in `.env` (see `.env.example`):

- `SECRET_KEY` — Django secret key
- `ENCRYPTION_KEY` — Fernet key for document-at-rest encryption (generate via `scripts/generate_encryption_key.sh`)
- `DB_*`, `REDIS_*` — Postgres/Redis credentials
- `HF_TOKEN` — optional Hugging Face token for gated models
- `DEBUG` — keep `False` outside development
- `ALLOWED_HOSTS` — comma-separated host list

## Architecture

```
nginx ──► web (Django + DRF, Gunicorn)
             │  ├─ Postgres 15 (documents metadata, chunks, vectors as JSON)
             │  ├─ Redis (cache + Celery broker)
             │  ├─ gpu_tasks (Celery, nvidia runtime) — LLM loading/inference
             │  └─ cpu_tasks (Celery) — parsing, embeddings, indexing
             └─ media/ (encrypted documents, downloaded models)

Retrieval pipeline: Fernet-decrypt → parse → chunk → BGE-M3 embeddings
→ FAISS (IndexFlatIP) + BM25 → hybrid merge → Qwen answer + citations
```

## Project layout

```
app/
  config/          Django project (settings, celery, urls, health)
  rag/             The application: models, views, DRF api_views,
                   Celery tasks, services (faiss, bm25, rag, embedding,
                   chat, document_parser, encryption), templates
prometheus/ grafana/ nginx/ scripts/ docker_volumes/
```

## Security notes

- Documents are encrypted with Fernet before hitting the disk; the key lives in `.env` — losing it makes stored documents unreadable.
- Keep `DEBUG=False` and set `ALLOWED_HOSTS` in any shared deployment.
- The default compose file binds helper UIs (pgAdmin, Flower, Grafana) to all interfaces — restrict or firewall them.

## Roadmap

See [ROADMAP.md](ROADMAP.md).

## License

MIT — see [LICENSE](LICENSE).

---

### README на русском

См. [README.ru.md](README.ru.md).
