ARG BUILD_FROM=python:3.11-slim
FROM ${BUILD_FROM}

WORKDIR /app

COPY run.py /app/run.py

RUN pip install --no-cache-dir requests

CMD ["python3", "/app/run.py"]
