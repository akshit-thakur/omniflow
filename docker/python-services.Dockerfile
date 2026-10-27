FROM python:3.12-slim AS dependencies

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /service
COPY api/requirements.txt requirements.txt
RUN pip install --no-cache-dir --requirement requirements.txt

FROM dependencies AS api-runtime
ARG SERVICE_UID=10001
ARG SERVICE_GID=10001
RUN addgroup --system --gid "$SERVICE_GID" app && adduser --system --uid "$SERVICE_UID" --ingroup app app
COPY api/app ./app
USER app
EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--no-access-log"]

FROM dependencies AS ai-runtime
ARG SERVICE_UID=10002
ARG SERVICE_GID=10002
RUN addgroup --system --gid "$SERVICE_GID" app && adduser --system --uid "$SERVICE_UID" --ingroup app app
COPY ai/app ./app
USER app
EXPOSE 8090
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8090", "--no-access-log"]
