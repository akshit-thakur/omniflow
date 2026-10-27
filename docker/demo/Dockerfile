FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /demo
COPY docker/demo/seed_showcase.py .
USER 10001:10001
CMD ["python", "seed_showcase.py"]
