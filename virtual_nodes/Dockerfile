FROM python:3.11-slim

WORKDIR /app

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PORT=8000

# Install iproute2 for tc netem network emulation
RUN apt-get update && apt-get install -y --no-install-recommends \
    iproute2 \
    curl \
    && rm -rf /var/lib/apt/lists/*

COPY pyproject.toml .
RUN pip install --no-cache-dir .

COPY edge/ ./edge/
COPY config/ ./config/

EXPOSE 8000

CMD ["uvicorn", "edge.agent:app", "--host", "0.0.0.0", "--port", "8000"]
