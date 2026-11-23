FROM python:3.12-slim-bookworm
WORKDIR /srv/ripplegate
COPY services/api/requirements.txt /srv/ripplegate/requirements.txt
RUN pip install --no-cache-dir -r requirements.txt
COPY services/api /srv/ripplegate/services/api
COPY services/worker /srv/ripplegate/services/worker
COPY services/runner /srv/ripplegate/services/runner
COPY db /srv/ripplegate/db
COPY examples /srv/ripplegate/examples
RUN useradd -r -u 10001 ripple
USER ripple
ENV PYTHONPATH=/srv/ripplegate/services/api:/srv/ripplegate/services/worker
CMD ["python", "-m", "celery", "-A", "celery_app", "worker", "--loglevel=info", "--concurrency=2"]
