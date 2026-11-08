#!/bin/bash
set -e

# Функция ожидания сервисов
wait_for_db() {
    echo "Waiting for PostgreSQL..."
    while ! nc -z db 5432; do
        sleep 0.5
    done
    echo "PostgreSQL started"
}

wait_for_redis() {
    echo "Waiting for Redis..."
    while ! nc -z redis 6379; do
        sleep 0.5
    done
    echo "Redis started"
}

wait_for_db
wait_for_redis

# Выполнение миграций и сборки статики только для web-сервера
if [ "$1" = "web" ] || [ "$1" = "gunicorn" ]; then
    echo "Running migrations and collecting static..."
    python manage.py migrate --noinput
    python manage.py collectstatic --noinput
fi

exec "$@"