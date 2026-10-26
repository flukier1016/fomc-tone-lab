# Dashboard + CLI in one image. Mount ./data to keep the store between runs:
#   docker build -t fomc-tone .
#   docker run --rm -p 127.0.0.1:8000:8000 -v "$PWD/data:/app/data" --env-file .env fomc-tone
FROM python:3.12-slim
WORKDIR /app
ENV PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1
COPY requirements.lock pyproject.toml ./
RUN pip install -r requirements.lock
COPY config ./config
COPY src ./src
RUN pip install -e . --no-deps
EXPOSE 8000
# Inside the container the server must listen on all interfaces; publish it on 127.0.0.1 only (see above).
CMD ["fomc", "serve", "--host", "0.0.0.0", "--port", "8000"]
