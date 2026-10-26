FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

COPY requirements.txt requirements-dev.txt ./
RUN python -m pip install --retries 10 --timeout 300 --index-url https://pypi.org/simple --prefer-binary -r requirements-dev.txt

COPY . .

# The compose file runs this image as your own uid/gid so files created by
# `makemigrations` in the bind mount belong to you, not root.
EXPOSE 8000
CMD ["gunicorn", "config.wsgi:application", "--bind", "0.0.0.0:8000", "--workers", "3"]
