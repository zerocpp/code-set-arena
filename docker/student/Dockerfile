FROM python:3.12-slim-bookworm

ARG PIP_INDEX_URL=https://pypi.org/simple
ARG PIP_DEFAULT_TIMEOUT=120

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    CODESETARENA_STUDENT_DATA_DIR=/data \
    PIP_INDEX_URL=${PIP_INDEX_URL} \
    PIP_DEFAULT_TIMEOUT=${PIP_DEFAULT_TIMEOUT} \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app
COPY pyproject.toml README.md /app/
COPY src /app/src
RUN python -m pip install --no-cache-dir .

EXPOSE 8000
CMD ["code-set-arena", "student", "serve", "--host", "0.0.0.0", "--port", "8000", "--data-dir", "/data"]
