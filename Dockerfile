ARG BUILD_FROM=ghcr.io/home-assistant/amd64-base:3.19
FROM ${BUILD_FROM}

WORKDIR /app

# HA base images are Alpine — use apk instead of pip (avoids missing pip / PEP 668 issues).
# tzdata: required for zoneinfo (e.g. Europe/Prague) in run.py.
RUN apk add --no-cache py3-requests tzdata

COPY run.py /app/run.py

CMD ["python3", "/app/run.py"]
