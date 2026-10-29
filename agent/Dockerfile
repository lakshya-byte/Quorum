FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PORT=8001

WORKDIR /srv/agent
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY app ./app
COPY guardrails ./guardrails
COPY scripts ./scripts
COPY evals ./evals
RUN mkdir -p runs .cache && chmod +x scripts/serve.sh

EXPOSE 8001
# newrelic-admin wraps uvicorn only when NEW_RELIC_LICENSE_KEY is set
CMD ["scripts/serve.sh"]
