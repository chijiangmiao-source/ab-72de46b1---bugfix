# syntax=docker/dockerfile:1

# ---- common base ----------------------------------------------------------
FROM python:3.11-slim AS base
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1
WORKDIR /srv

# ---- audit service runtime ------------------------------------------------
FROM base AS runtime
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY app ./app
EXPOSE 8000
# The container is healthy only once the request validator AND the scan
# engine both report ready (see app/healthcheck.py).
HEALTHCHECK --interval=5s --timeout=3s --start-period=3s --retries=12 \
    CMD ["python", "-m", "app.healthcheck"]
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]

# ---- one-shot verification image ------------------------------------------
FROM runtime AS verify
COPY requirements-verify.txt .
RUN pip install --no-cache-dir -r requirements-verify.txt
COPY tests ./tests
COPY verify ./verify
COPY pytest.ini ./pytest.ini
# Runs the test suite, build check and API/HTTP smoke once, then exits;
# the process exit code is the verification result.
CMD ["python", "verify/run_verify.py"]
