# syntax=docker/dockerfile:1

# --------------------------------------------------------------------------
# Stage 1: build the browser UI
#
# The Python image never needs Node, so the toolchain and node_modules are
# left behind in this stage and only the compiled page is carried forward.
# --------------------------------------------------------------------------
FROM node:22-alpine AS web-build

WORKDIR /build

# Copy the manifests first so this layer is cached until dependencies change.
COPY web/package.json web/package-lock.json ./
RUN npm ci --no-audit --no-fund

COPY web/ ./
RUN npm run build


# --------------------------------------------------------------------------
# Stage 2: the runtime
# --------------------------------------------------------------------------
FROM python:3.12-slim AS runtime

# A fixed id keeps ownership predictable when a volume is created from the image.
ARG APP_UID=10001
ARG APP_GID=10001

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    # Inside a container the loopback default would leave the server unreachable.
    CHAT_BIND_HOST=0.0.0.0 \
    CHAT_LOG_LEVEL=INFO

WORKDIR /app

RUN groupadd --gid "${APP_GID}" tspo \
    && useradd --uid "${APP_UID}" --gid "${APP_GID}" --no-create-home --shell /usr/sbin/nologin tspo

COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY server/ ./server/
COPY client/ ./client/
COPY scripts/loadtest.py ./scripts/loadtest.py
COPY --from=web-build /build/dist ./web/dist

# Create the writable directories inside the image so that a fresh named volume
# inherits this ownership. Without this the volume would be owned by root and
# the unprivileged user could not write the database or the log.
RUN mkdir -p /app/data /app/logs \
    && chown -R "${APP_UID}:${APP_GID}" /app/data /app/logs

USER tspo

# 8000 serves the REST API and the browser UI, 8765 is the chat socket.
EXPOSE 8000 8765

# Python is already here, so the check needs no extra packages in the image.
HEALTHCHECK --interval=30s --timeout=5s --start-period=15s --retries=3 \
    CMD ["python", "-c", "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/health', timeout=4).status == 200 else 1)"]

CMD ["python", "server/server.py"]
