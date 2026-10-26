# syntax=docker/dockerfile:1
# Pin by tag here; Dependabot (docker ecosystem) proposes digest-pinned updates.

# ---- Stage 1: prepare a minimal, cleaned runtime filesystem -------------------------------
FROM python:3.13-slim AS prepare

# Unprivileged user with a fixed UID so Kubernetes runAsUser/runAsNonRoot checks can be explicit.
# The app is stdlib-only, so the package installers are removed: Trivy flagged fixable HIGH CVEs in
# pip/setuptools and the libraries vendored inside them (urllib3, msgpack), and nothing here needs
# them at runtime. ensurepip goes too: its bundled pip wheel carries the same vendored libraries.
RUN groupadd --gid 10001 app \
    && useradd --uid 10001 --gid app --no-create-home --shell /usr/sbin/nologin app \
    && python -m pip uninstall --yes pip setuptools wheel \
    && rm -rf /usr/local/lib/python3.13/site-packages/pip* \
              /usr/local/lib/python3.13/site-packages/setuptools* \
              /usr/local/lib/python3.13/site-packages/pkg_resources* \
              /usr/local/lib/python3.13/site-packages/_distutils_hack* \
              /usr/local/lib/python3.13/site-packages/wheel* \
              /usr/local/lib/python3.13/ensurepip \
              /usr/local/bin/pip*

WORKDIR /app
COPY --chown=app:app app/server.py ./server.py

# ---- Stage 2: flatten into ONE fresh layer ------------------------------------------------
# Deleting files in a later layer only hides them: the base layer still contains them, and scanners
# that read layers (Trivy did) keep reporting packages that no longer exist in the running image.
# Copying the finished filesystem into a new layer makes the image contain exactly what runs.
FROM scratch AS runtime
COPY --from=prepare / /

ARG APP_VERSION=dev
ENV PATH=/usr/local/bin:/usr/local/sbin:/usr/sbin:/usr/bin:/sbin:/bin \
    LANG=C.UTF-8 \
    APP_VERSION=${APP_VERSION} \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PORT=8080

WORKDIR /app
USER 10001:10001
EXPOSE 8080

HEALTHCHECK --interval=15s --timeout=3s --start-period=5s --retries=3 \
  CMD ["python", "-c", "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8080/healthz', timeout=2).status == 200 else 1)"]

CMD ["python", "server.py"]
