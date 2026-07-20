FROM python:3.13-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    ARKA_HOSTED_MODE=1 \
    ARKA_REMOTE_PROFILE=coding \
    ARKA_MCP_ENABLE_PERSONAL_SKILLS=0 \
    REMOTE_HOST=0.0.0.0

WORKDIR /app

RUN apt-get update \
    && apt-get install -y --no-install-recommends git fish curl ca-certificates \
    && rm -rf /var/lib/apt/lists/*

COPY pyproject.toml README.md ./
COPY src ./src

RUN pip install --no-cache-dir -e ".[dev]"

EXPOSE 8765

CMD ["python", "-m", "arka.integrations.remote_server", "serve"]
