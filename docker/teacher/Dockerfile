FROM python:3.12-slim-bookworm AS deps

ARG PIP_INDEX_URL=https://pypi.org/simple
ARG PIP_DEFAULT_TIMEOUT=120

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    CODESETARENA_TEACHER_DATA_DIR=/data \
    PIP_INDEX_URL=${PIP_INDEX_URL} \
    PIP_DEFAULT_TIMEOUT=${PIP_DEFAULT_TIMEOUT} \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app
COPY requirements.txt /app/
RUN python -m pip install --no-cache-dir -r requirements.txt

FROM deps AS app
WORKDIR /app
COPY pyproject.toml README.md /app/
COPY src /app/src
RUN python -m pip install --no-cache-dir --no-deps .

EXPOSE 8010
CMD ["code-set-arena", "teacher", "serve", "--host", "0.0.0.0", "--port", "8010", "--data-dir", "/data"]
