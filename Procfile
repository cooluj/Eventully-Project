web: gunicorn --workers 1 --threads 8 --timeout 60 app:app
release: flask --app app seed-db
