# Project RAG Search

RAG-поисковик с поддержкой LLM (Qwen 3.5-4B), эмбеддингов BGE-M3, шифрованием документов и разделением на GPU/CPU воркеры.

## Быстрый старт

1. Скопировать `.env.example` в `.env` и заполнить переменные.
2. Сгенерировать ключ шифрования: `./scripts/generate_encryption_key.sh` и добавить в `.env`.
3. Запустить: `docker-compose up -d`
4. Создать суперпользователя: `docker exec -it rag_web python manage.py createsuperuser`
5. Открыть http://localhost

## Остановка

`docker-compose down`