release: python manage.py migrate
web: gunicorn django_tracker.wsgi --max-requests 500 --max-requests-jitter 50
worker: REMAP_SIGTERM=SIGQUIT celery --app django_tracker.celery.app worker --loglevel=info