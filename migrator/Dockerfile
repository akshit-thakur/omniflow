FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /migrator

COPY requirements.txt .
RUN pip install --no-cache-dir --requirement requirements.txt

COPY alembic.ini .
COPY alembic ./alembic
COPY database ./database
COPY scripts/run_migrations.py ./scripts/run_migrations.py
COPY scripts/check_constraints.py ./scripts/check_constraints.py

CMD ["python", "scripts/run_migrations.py"]
