FROM alpine:3.21
COPY scripts/startup/init_secrets.sh /opt/omniflow/init_secrets.sh
ENTRYPOINT ["/bin/sh", "/opt/omniflow/init_secrets.sh"]
