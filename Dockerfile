# The browser GUI as a server, for running behind a reverse proxy that ends TLS (docs/deployment.md).
#
#   docker build -t py-tbparse .
#   docker run --rm -p 8080:8080 --read-only --tmpfs /tmp:size=512m \
#       -e PY_TBPARSE_ALLOWED_HOSTS=tbparse.example.com py-tbparse

FROM python:3.12-slim AS build
WORKDIR /src
COPY pyproject.toml MANIFEST.in README.md LICENSE ./
COPY py_tbparse ./py_tbparse
RUN pip wheel --no-cache-dir --wheel-dir /wheels .

FROM python:3.12-slim
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PY_TBPARSE_SERVER_MODE=1 \
    PY_TBPARSE_TRUST_PROXY=1
RUN --mount=type=bind,from=build,source=/wheels,target=/wheels \
    pip install /wheels/*.whl \
    && useradd --system --uid 10001 --no-create-home --shell /usr/sbin/nologin tbparse
USER 10001
EXPOSE 8080
HEALTHCHECK --interval=30s --timeout=3s --start-period=5s \
    CMD ["python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8080/healthz', timeout=2)"]
# Uploads are written under TMPDIR; mount it as a tmpfs (or a volume) when the root filesystem is read-only.
ENTRYPOINT ["py-tbparse-gui", "--host", "0.0.0.0", "--port", "8080", "--no-browser"]
