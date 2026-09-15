#!/bin/sh
set -eu

attempts=${MODEL_PULL_ATTEMPTS:-5}
pull_timeout=${MODEL_PULL_TIMEOUT_SECONDS:-3600}

validate_positive_integer() {
    name=$1
    value=$2
    case "$value" in
        ''|*[!0-9]*)
            echo "$name must be a positive integer." >&2
            exit 2
            ;;
    esac
    if [ "$value" -lt 1 ]; then
        echo "$name must be a positive integer." >&2
        exit 2
    fi
}

validate_positive_integer MODEL_PULL_ATTEMPTS "$attempts"
validate_positive_integer MODEL_PULL_TIMEOUT_SECONDS "$pull_timeout"

embedding_model=${OLLAMA_EMBED_MODEL:-}
case "$embedding_model" in
    bge-m3|bge-m3:?*)
        ;;
    *)
        echo "OLLAMA_EMBED_MODEL must be bge-m3 (optionally with a non-empty tag)." >&2
        exit 2
        ;;
esac

ensure_model() {
    model=$1
    if [ -z "$model" ]; then
        echo "A configured Ollama model name is empty." >&2
        exit 2
    fi

    if ollama show "$model" >/dev/null 2>&1; then
        echo "Ollama model $model is already available."
        return
    fi

    attempt=1
    while [ "$attempt" -le "$attempts" ]; do
        echo "Pulling Ollama model $model (attempt $attempt/$attempts)."
        if timeout --signal=TERM --kill-after=30 "$pull_timeout" \
            ollama pull "$model" \
            && ollama show "$model" >/dev/null 2>&1; then
            return
        fi
        if [ "$attempt" -lt "$attempts" ]; then
            delay=$((attempt * 5))
            if [ "$delay" -gt 30 ]; then
                delay=30
            fi
            sleep "$delay"
        fi
        attempt=$((attempt + 1))
    done

    echo "Unable to make Ollama model $model available after $attempts attempts." >&2
    exit 1
}

ensure_model "$embedding_model"
ensure_model "${OLLAMA_REASONER_MODEL:-}"
