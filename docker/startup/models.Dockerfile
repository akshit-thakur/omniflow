FROM ollama/ollama:0.32.4
COPY scripts/startup/init_models.sh /opt/omniflow/init_models.sh
ENTRYPOINT ["/bin/sh", "/opt/omniflow/init_models.sh"]
