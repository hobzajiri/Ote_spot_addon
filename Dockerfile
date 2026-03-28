ARG BUILD_FROM=ghcr.io/home-assistant/amd64-base:3.19
FROM ${BUILD_FROM}

WORKDIR /app

ENV PYTHONUNBUFFERED=1

# HA base images are Alpine — use apk instead of pip (avoids missing pip / PEP 668 issues).
# tzdata: required for zoneinfo (e.g. Europe/Prague) in run.py.
RUN apk add --no-cache py3-requests tzdata

COPY run.py /app/run.py

# s6 longrun: stdout/stderr show up reliably in the Home Assistant add-on log (CMD alone is often fully buffered).
COPY rootfs /
RUN chmod a+x /etc/services.d/ote-spot/run
