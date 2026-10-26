# syntax=docker/dockerfile:1
# Zero third-party dependencies, so there is no build stage and nothing to `pip install`.
# Hardening next step: pin the base image by digest (python:3.13-slim@sha256:...) and let
# Dependabot/Renovate bump it.
FROM python:3.13-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

RUN groupadd --system --gid 10001 app && useradd --system --uid 10001 --gid app --no-create-home app

WORKDIR /app
COPY gateway/ ./gateway/

USER 10001:10001
EXPOSE 8080

HEALTHCHECK --interval=15s --timeout=3s --start-period=5s --retries=3 \
  CMD ["python", "-c", "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8080/healthz', timeout=2).status == 200 else 1)"]

CMD ["python", "-m", "gateway"]
