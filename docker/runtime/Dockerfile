FROM python:3.12-slim-bookworm

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

RUN useradd --create-home --uid 1000 runner
WORKDIR /runner
COPY docker/runtime/run_case.py /runner/run_case.py
USER runner

CMD ["python", "/runner/run_case.py"]
