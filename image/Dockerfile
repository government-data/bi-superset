# The bi-superset image (core decision 0089, point 6): Apache Superset 6.1.0,
# pinned by digest, with what it lacks: the Trino driver, the OIDC client
# library and the PostgreSQL driver, each pinned, and the module's
# configuration. Built from the repository's root:
#
#   docker build -f image/Dockerfile -t bi-superset .
FROM apache/superset:6.1.0@sha256:16b50bbef6648912a79e3293d418fefa743ce555d36c5af6b85d859119ed7f88

USER root
RUN uv pip install --python /app/.venv/bin/python --no-cache \
      trino==0.340.0 \
      authlib==1.9.4 \
      psycopg2-binary==2.9.9
# Superset reads /app/pythonpath/superset_config.py (its PYTHONPATH).
COPY --chown=root:root --chmod=0444 config/superset_config.py /app/pythonpath/superset_config.py
COPY --chown=root:root --chmod=0444 init/superset_init.py /app/qd/superset_init.py
USER superset
