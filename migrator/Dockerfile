FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /migrator

COPY requirements.txt .
RUN pip install --no-cache-dir --requirement requirements.txt

COPY alembic.ini .
COPY alembic ./alembic
COPY database ./database
COPY scripts/startup/run_migrations.py ./scripts/startup/run_migrations.py

CMD ["python", "-m", "scripts.startup.run_migrations"]
