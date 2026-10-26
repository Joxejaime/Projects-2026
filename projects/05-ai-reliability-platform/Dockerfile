# syntax=docker/dockerfile:1
# Hardening next step: pin the base image by digest (python:3.13-slim@sha256:...) and let
# Dependabot/Renovate bump it.

# ---- Stage 1: prepare a minimal, cleaned runtime filesystem -------------------------------
FROM python:3.13-slim AS prepare

# The gateway has zero third-party dependencies, so nothing needs installing and the package
# installers can go: Trivy flags fixable HIGH CVEs in pip/setuptools and the libraries vendored
# inside them (urllib3, msgpack). ensurepip goes too, since its bundled pip wheel carries the same
# libraries and Trivy scans inside wheels.
RUN groupadd --system --gid 10001 app \
    && useradd --system --uid 10001 --gid app --no-create-home app \
    && python -m pip uninstall --yes pip setuptools wheel \
    && rm -rf /usr/local/lib/python3.13/site-packages/pip* \
              /usr/local/lib/python3.13/site-packages/setuptools* \
              /usr/local/lib/python3.13/site-packages/pkg_resources* \
              /usr/local/lib/python3.13/site-packages/_distutils_hack* \
              /usr/local/lib/python3.13/site-packages/wheel* \
              /usr/local/lib/python3.13/ensurepip \
              /usr/local/bin/pip*

WORKDIR /app
COPY gateway/ ./gateway/

# ---- Stage 2: flatten into ONE fresh layer ------------------------------------------------
# Deleting files in a later layer only hides them: the base layer still holds them, and scanners
# that read layers keep reporting packages that are no longer in the running image. Copying the
# finished filesystem into a new layer makes the image contain exactly what runs.
FROM scratch AS runtime
COPY --from=prepare / /

ENV PATH=/usr/local/bin:/usr/local/sbin:/usr/sbin:/usr/bin:/sbin:/bin \
    LANG=C.UTF-8 \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app
USER 10001:10001
EXPOSE 8080

HEALTHCHECK --interval=15s --timeout=3s --start-period=5s --retries=3 \
  CMD ["python", "-c", "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8080/healthz', timeout=2).status == 200 else 1)"]

CMD ["python", "-m", "gateway"]
