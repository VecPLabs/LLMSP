FROM python:3.11-slim

LABEL maintainer="David Cappelli <davidcappelli@vecplabs.com>"
LABEL description="LLMSP: LLM Swarm Protocol runtime"

WORKDIR /app

# System deps for cryptography wheel
RUN apt-get update && \
    apt-get install -y --no-install-recommends gcc libffi-dev && \
    rm -rf /var/lib/apt/lists/*

COPY pyproject.toml .
COPY llmsp/ llmsp/

RUN pip install --no-cache-dir -e . && \
    apt-get purge -y gcc && apt-get autoremove -y

# Persistent volumes for SQLite databases
VOLUME ["/data"]
ENV LLMSP_DB_DIR=/data

ENTRYPOINT ["python", "-m", "llmsp.cli"]
CMD ["--help"]
