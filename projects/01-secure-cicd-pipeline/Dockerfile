# syntax=docker/dockerfile:1
# Pin by tag here; Dependabot (docker ecosystem) proposes digest-pinned updates.
FROM python:3.13-slim AS runtime

ARG APP_VERSION=dev
ENV APP_VERSION=${APP_VERSION} \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PORT=8080

# Unprivileged user with a fixed UID so Kubernetes runAsUser/runAsNonRoot checks can be explicit.
# The app is stdlib-only, so the package installers are removed from the runtime image: Trivy flagged
# fixable HIGH CVEs in pip/setuptools and the libraries vendored inside them (urllib3, msgpack),
# and nothing here needs them at runtime.
RUN groupadd --gid 10001 app \
    && useradd --uid 10001 --gid app --no-create-home --shell /usr/sbin/nologin app \
    && python -m pip uninstall --yes pip setuptools wheel \
    && rm -rf /usr/local/lib/python3.13/site-packages/pip* \
              /usr/local/lib/python3.13/site-packages/setuptools* \
              /usr/local/lib/python3.13/site-packages/pkg_resources* \
              /usr/local/lib/python3.13/site-packages/_distutils_hack* \
              /usr/local/lib/python3.13/site-packages/wheel* \
              /usr/local/bin/pip*

WORKDIR /app
COPY --chown=app:app app/server.py ./server.py

USER 10001:10001
EXPOSE 8080

HEALTHCHECK --interval=15s --timeout=3s --start-period=5s --retries=3 \
  CMD ["python", "-c", "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8080/healthz', timeout=2).status == 200 else 1)"]

CMD ["python", "server.py"]
