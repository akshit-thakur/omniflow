#!/bin/sh
set -eu

repository_dir=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
cd "$repository_dir"

demo_port=${OMNIFLOW_DEMO_PORT:-3002}
model_volume=${SHOWCASE_OLLAMA_MODELS_VOLUME:-omniflow_ollama-models}
export OMNIFLOW_PORT="$demo_port"
export SHOWCASE_OLLAMA_MODELS_VOLUME="$model_volume"

if ! docker volume inspect "$model_volume" >/dev/null 2>&1; then
    echo "Creating local Ollama model cache: $model_volume"
    docker volume create "$model_volume" >/dev/null
fi

echo "Validating the isolated showcase configuration..."
docker compose -f compose.showcase.yaml config --quiet

echo "Starting Omniflow and the local Ollama models..."
docker compose -f compose.showcase.yaml up --build --detach

echo "Creating the showcase data and synchronizing its AI index..."
docker compose -f compose.showcase.yaml --profile tools run --build --rm showcase-seed

demo_url="http://127.0.0.1:$demo_port"
attempt=1
health_ready=false
while [ "$attempt" -le 30 ]; do
    if curl --fail --silent --show-error "$demo_url/healthz" >/dev/null \
        && curl --fail --silent --show-error "$demo_url/readyz" >/dev/null; then
        health_ready=true
        break
    fi
    attempt=$((attempt + 1))
    sleep 2
done

if [ "$health_ready" != "true" ]; then
    echo "The demo started, but its public health checks did not become ready." >&2
    echo "Inspect it with: docker compose -f compose.showcase.yaml ps --all" >&2
    exit 1
fi

echo "Omniflow demo is ready at $demo_url"
if [ "${1:-}" = "--open" ]; then
    open "$demo_url"
fi
