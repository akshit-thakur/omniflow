#!/bin/sh
set -eu

# Compose-owned secrets live beside the data volumes so a missing or copied
# Environment changes cannot silently change credentials for an existing installation.
# Values are never printed.
mkdir -p /run/omniflow-admin /run/omniflow-api /run/omniflow-ai
chmod 0700 /run/omniflow-admin /run/omniflow-api /run/omniflow-ai
chown 10001:10001 /run/omniflow-api
chown 10002:10002 /run/omniflow-ai

generate_secret() {
    # BusyBox (Alpine) provides od and tr, so this has no package dependency.
    od -An -N32 -tx1 /dev/urandom | tr -d ' \n'
}

is_placeholder() {
    case "$1" in
        ""|omniflow_password|development-only-secret|replace-with-a-strong-password|replace-with-a-long-random-secret)
            return 0
            ;;
    esac
    return 1
}

install_secret() {
    name=$1
    supplied=$2
    minimum_length=$3
    secret_dir=$4
    destination="$secret_dir/$name"
    if [ -e "$destination" ] && [ ! -f "$destination" ]; then
        echo "$destination exists but is not a regular file." >&2
        exit 2
    fi
    if [ -s "$destination" ]; then
        echo "Keeping the existing $name secret."
        return
    fi
    single_line=$(printf '%s' "$supplied" | tr -d '\r\n')
    if [ "$single_line" != "$supplied" ]; then
        echo "$name input must contain exactly one line." >&2
        exit 2
    fi
    if ! is_placeholder "$supplied" && [ "${#supplied}" -ge "$minimum_length" ]; then
        value=$supplied
        source=configured
    else
        value=$(generate_secret)
        source=generated
    fi
    temporary="$destination.tmp.$$"
    printf '%s\n' "$value" > "$temporary"
    chmod 0400 "$temporary"
    mv "$temporary" "$destination"
    echo "Installed $source $name secret."
}

install_secret admin_password "${ADMIN_PASSWORD_INPUT:-}" 16 /run/omniflow-admin
install_secret database_password "${API_PASSWORD_INPUT:-}" 24 /run/omniflow-api
install_secret database_password "${AI_PASSWORD_INPUT:-}" 24 /run/omniflow-ai
service_secret_file=/run/omniflow-api/ai_service_secret
other_service_secret_file=/run/omniflow-ai/ai_service_secret
if [ -s "$service_secret_file" ] && [ -s "$other_service_secret_file" ]; then
    if ! cmp -s "$service_secret_file" "$other_service_secret_file"; then
        echo "Existing API and AI service secrets conflict; reconcile them explicitly before starting." >&2
        exit 2
    fi
elif [ -s "$service_secret_file" ]; then
    cp "$service_secret_file" "$other_service_secret_file"
    chmod 0400 "$other_service_secret_file"
elif [ -s "$other_service_secret_file" ]; then
    cp "$other_service_secret_file" "$service_secret_file"
    chmod 0400 "$service_secret_file"
else
    install_secret ai_service_secret "${AI_SERVICE_SECRET_INPUT:-}" 32 /run/omniflow-api
    cp "$service_secret_file" "$other_service_secret_file"
    chmod 0400 "$other_service_secret_file"
fi
test -s /run/omniflow-admin/admin_password
test -s /run/omniflow-api/database_password
test -s /run/omniflow-api/ai_service_secret
test -s /run/omniflow-ai/database_password
test -s /run/omniflow-ai/ai_service_secret
chown 10001:10001 /run/omniflow-api/*
chown 10002:10002 /run/omniflow-ai/*
