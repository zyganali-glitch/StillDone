# syntax=docker/dockerfile:1
FROM --platform=linux/arm64 python:3.13-slim-bookworm

# Security: prevent Python from writing .pyc and enable unbuffered output
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PORT=8000

# Set working directory
WORKDIR /app

# Create a non-root system user and group
RUN groupadd -r stilldone && useradd -r -g stilldone -d /app -s /sbin/nologin stilldone

# Install build dependencies, copy project definition, and install StillDone
COPY pyproject.toml README.md ./
COPY src/ ./src/

RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir .

# Change ownership to non-root user
RUN chown -R stilldone:stilldone /app /tmp

# Switch to non-root user
USER stilldone

# Expose canonical AgentCore MCP port
EXPOSE 8000

# Run StillDone under the explicit AgentCore deployment profile (0.0.0.0:8000, /mcp, /ping, rate-limited)
CMD ["python", "-m", "stilldone", "--profile", "agentcore"]
