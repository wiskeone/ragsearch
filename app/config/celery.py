from __future__ import absolute_import, unicode_literals
import os
from celery import Celery

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')

app = Celery('config')
app.config_from_object('django.conf:settings', namespace='CELERY')
app.autodiscover_tasks()

app.conf.task_queues = {
    'gpu_tasks': {'exchange': 'gpu_tasks', 'routing_key': 'gpu_tasks'},
    'cpu_tasks': {'exchange': 'cpu_tasks', 'routing_key': 'cpu_tasks'},
}

# Маршрутизация не нужна – декораторы задач сами указывают очередь
app.conf.task_routes = {}

app.conf.task_acks_late = True
app.conf.task_reject_on_worker_lost = True
app.conf.task_track_started = True
app.conf.result_expires = 3600