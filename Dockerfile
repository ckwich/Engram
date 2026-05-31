# syntax=docker/dockerfile:1

FROM python:3.12-slim-bookworm AS base

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

RUN groupadd --system --gid 10001 engram \
    && useradd --system --uid 10001 --gid engram --home-dir /var/lib/engram --create-home engram \
    && python -m pip install --upgrade pip

FROM base AS thin-client

COPY requirements-daemon-client.txt ./
RUN pip install --no-cache-dir -r requirements-daemon-client.txt

COPY --chown=engram:engram server_daemon_client.py ./
COPY --chown=engram:engram core ./core
COPY --chown=engram:engram scripts/smoke_mcp_thin_client.py ./scripts/smoke_mcp_thin_client.py

ENV ENGRAM_DAEMON_URL=http://engramd-core:8765

USER engram

CMD ["python", "server_daemon_client.py"]

FROM base AS engramd-core

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        build-essential \
        curl \
        git \
        poppler-utils \
        tesseract-ocr \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt requirements-core.txt requirements-dashboard.txt requirements-daemon-client.txt ./
RUN pip install --no-cache-dir --index-url https://download.pytorch.org/whl/cpu "torch==2.12.0+cpu"
RUN pip install --no-cache-dir -r requirements.txt

COPY --chown=engram:engram . .

ENV ENGRAM_DATA_DIR=/var/lib/engram
ENV HF_HOME=/var/lib/engram/model-cache
ENV TRANSFORMERS_CACHE=/var/lib/engram/model-cache
ENV ENGRAM_DAEMON_URL=http://127.0.0.1:8765

RUN mkdir -p /var/lib/engram/model-cache \
    && chown -R engram:engram /var/lib/engram /app

VOLUME ["/var/lib/engram"]
EXPOSE 8765

HEALTHCHECK --interval=30s --timeout=10s --start-period=30s --retries=3 \
    CMD python engramd.py --health --host 127.0.0.1 --port 8765 || exit 1

USER engram

CMD ["python", "engramd.py", "--host", "127.0.0.1", "--port", "8765"]

FROM engramd-core AS web-inspector

ENV ENGRAM_DAEMON_URL=http://engramd-core:8765

HEALTHCHECK --interval=30s --timeout=10s --start-period=30s --retries=3 \
    CMD curl -fsS -H "X-Engram-Access-Token: ${ENGRAM_WEBUI_ACCESS_TOKEN}" http://127.0.0.1:5000/health >/dev/null || exit 1

CMD ["python", "webui.py"]
