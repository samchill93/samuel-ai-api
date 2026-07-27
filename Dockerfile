# syntax=docker/dockerfile:1
#
# Reproducible image for the "Ask Me About Samuel" API (Module 7).
# A single slim stage is the right size: this is a pure-Python app with no build/compile
# step, so a multi-stage build would add complexity for no smaller image. Dependencies are
# installed in their own layer (cached across code changes), the app runs as a non-root user,
# and the container never contains secrets — those are injected at runtime as environment
# variables (see .dockerignore, which keeps .env out of the image).

FROM python:3.12-slim AS runtime

# No .pyc files; unbuffered stdout so logs stream straight to the container runtime.
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

# Dependencies first, in their own layer, so editing code doesn't reinstall them.
COPY requirements.txt .
RUN pip install -r requirements.txt

# Then the application code (the frequently-changing layer).
COPY . .

# Never run the app as root in a container.
RUN useradd --create-home --uid 10001 appuser && chown -R appuser /app
USER appuser

# Render and most PaaS inject $PORT; default to 8000 for local runs.
ENV PORT=8000
EXPOSE 8000

# Liveness against the same /health endpoint the site's telemetry uses (stdlib only, no curl).
HEALTHCHECK --interval=30s --timeout=5s --start-period=15s --retries=3 \
    CMD python -c "import os,urllib.request; urllib.request.urlopen('http://127.0.0.1:'+os.environ.get('PORT','8000')+'/health')"

# Shell form so ${PORT} expands at runtime.
CMD uvicorn main:app --host 0.0.0.0 --port ${PORT:-8000}
