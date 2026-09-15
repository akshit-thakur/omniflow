FROM python:3.12-slim AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /service
RUN addgroup --system --gid 10002 app && adduser --system --uid 10002 --ingroup app app

COPY requirements.txt .
RUN pip install --no-cache-dir --requirement requirements.txt
COPY app ./app

USER app
EXPOSE 8090
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8090", "--no-access-log"]
