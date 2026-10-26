# Hosted, read-only dashboard (Railway, Fly, Render...). The store ships inside the image:
# deploy/fomc.db.gz is a vacuumed snapshot made by `make deploy-snapshot`.
FROM python:3.12-slim
WORKDIR /app
ENV PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1 PYTHONPATH=/app/src FOMC_PUBLIC=1
COPY requirements-serve.txt requirements.lock ./
RUN pip install -r requirements-serve.txt -c requirements.lock
COPY config ./config
COPY src ./src
COPY deploy/fomc.db.gz /tmp/fomc.db.gz
RUN mkdir -p data && gunzip -c /tmp/fomc.db.gz > data/fomc.db && rm /tmp/fomc.db.gz \
    && python -c "from fomc import db; c = db.connect(); db.init(c); db.checkpoint(c); print('store ready')"
EXPOSE 8000
CMD ["sh", "-c", "exec uvicorn fomc.api:app --host 0.0.0.0 --port ${PORT:-8000} --proxy-headers --forwarded-allow-ips '*'"]
