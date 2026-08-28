# Container image for Cloud Run, Hugging Face Spaces, Fly.io, or anywhere else
# that takes a Dockerfile. One process, so the rate limiter and sessions work
# the way they are written.

FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

COPY requirements.txt requirements-web.txt ./
# Matplotlib is only needed by the command line figure scripts, not the web
# interface, so it is left out to keep the image small.
RUN grep -v -i '^matplotlib' requirements.txt > /tmp/core.txt \
    && pip install --no-cache-dir -r /tmp/core.txt -r requirements-web.txt

COPY aggsim/ ./aggsim/
COPY web/ ./web/
COPY wsgi.py ./

# Messages need a durable path. Mount a volume here, or leave it and the
# contact form disables itself rather than losing what people write.
ENV AGGSIM_MESSAGE_STORE=/data/messages.jsonl
RUN mkdir -p /data && chown -R 1000:1000 /data

# Never run as root, and never with the development server.
RUN useradd -u 1000 -m appuser
USER appuser

EXPOSE 8080
ENV AGGSIM_PORT=8080
CMD ["sh", "-c", "gunicorn -w 2 -t 60 -b 0.0.0.0:${PORT:-8080} wsgi:app"]
