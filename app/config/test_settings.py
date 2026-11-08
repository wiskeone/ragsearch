"""v2.0: CI-настройки — sqlite вместо Postgres, минимум сервисов.

Запуск: python manage.py test rag.tests --settings=config.test_settings
"""
from .settings import *  # noqa: F401,F403

DATABASES = {
    'default': {
        'ENGINE': 'django.db.backends.sqlite3',
        'NAME': '/tmp/ragsearch_test.sqlite3',
    }
}
CACHES = {
    'default': {'BACKEND': 'django.core.cache.backends.locmem.LocMemCache'}
}
# тяжёлые интеграции в тестах не нужны
CELERY_TASK_ALWAYS_EAGER = True
REST_FRAMEWORK = {**REST_FRAMEWORK}  # noqa: F405
