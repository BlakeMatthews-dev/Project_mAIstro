FROM python:3.12-slim AS base

WORKDIR /app

# System deps
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl git && \
    rm -rf /var/lib/apt/lists/*

# Install gitleaks for skill scanning
ARG GITLEAKS_VERSION=8.24.3
RUN curl -sSfL "https://github.com/gitleaks/gitleaks/releases/download/v${GITLEAKS_VERSION}/gitleaks_${GITLEAKS_VERSION}_linux_x64.tar.gz" \
    | tar xz -C /usr/local/bin gitleaks

# Python deps
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Application code
COPY gateway/ /app/gateway/
COPY orchestrator/ /app/orchestrator/

# Non-root user for production
RUN useradd -m conductor
USER conductor

# Health check
HEALTHCHECK --interval=30s --timeout=5s --retries=3 \
    CMD curl -sf http://localhost:9090/health || exit 1

EXPOSE 9090

# Default: run the gateway. Override CMD for orchestrator.
CMD ["uvicorn", "gateway.server:app", "--host", "0.0.0.0", "--port", "9090"]
