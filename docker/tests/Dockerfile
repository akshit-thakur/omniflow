FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /workspace
COPY api/requirements.txt /tmp/api-requirements.txt
COPY ai/requirements.txt /tmp/ai-requirements.txt
COPY requirements.txt /tmp/migration-requirements.txt
RUN pip install --no-cache-dir -r /tmp/api-requirements.txt -r /tmp/ai-requirements.txt -r /tmp/migration-requirements.txt
COPY api api
COPY ai ai
COPY tests tests
COPY scripts scripts
COPY docker/tests docker/tests
COPY docker/demo docker/demo
COPY alembic alembic
COPY alembic.ini .
COPY database database
COPY frontend/src frontend/src
COPY frontend/nginx.conf frontend/vite.config.ts frontend/
CMD ["python", "-m", "unittest", "discover", "-s", "tests", "-v"]
