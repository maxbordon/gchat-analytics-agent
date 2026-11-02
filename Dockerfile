FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PORT=8080

WORKDIR /srv

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app/ app/
COPY config/ config/
COPY examples/ examples/

# Run as a non-root user.
RUN useradd --create-home bot
USER bot

# Few workers, more threads: the work is mostly waiting on network I/O.
CMD exec gunicorn --bind :${PORT} --workers 1 --threads 8 --timeout 0 "app.main:create_app()"
