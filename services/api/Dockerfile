FROM python:3.12-slim-bookworm
# non-root, pinned, lean; no Docker socket ever mounted (see SECURITY.md)
WORKDIR /srv/ripplegate
COPY services/api/requirements.txt /srv/ripplegate/requirements.txt
RUN pip install --no-cache-dir -r requirements.txt
COPY services/api /srv/ripplegate/services/api
COPY db /srv/ripplegate/db
COPY examples /srv/ripplegate/examples
COPY services/runner /srv/ripplegate/services/runner
RUN useradd -r -u 10001 ripple && mkdir -p /var/lib/ripplegate/artifacts \
    && chown -R ripple /var/lib/ripplegate /srv/ripplegate
USER ripple
ENV PYTHONPATH=/srv/ripplegate/services/api
EXPOSE 8000
HEALTHCHECK --interval=15s --timeout=5s --retries=5 \
  CMD python -c "import urllib.request;urllib.request.urlopen('http://127.0.0.1:8000/api/v1/health').read()" || exit 1
CMD ["python", "-m", "uvicorn", "app.main:create_app", "--factory", "--host", "0.0.0.0", "--port", "8000"]
