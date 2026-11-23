# Trusted launcher image for controlled consumer fixtures (spec 10.2).
# The API/web containers NEVER mount the Docker socket; this launcher is run
# by the operator/CI host context only.
FROM node:22-bookworm-slim
WORKDIR /suite
COPY examples /suite-examples
RUN useradd -r -u 10001 fixture \
    && chown -R fixture /suite
USER fixture
# suites execute with: --network none --cap-drop ALL --read-only --tmpfs /tmp
# fixed argv vector; no arbitrary commands accepted (allowlist.py)
CMD ["node", "--version"]
