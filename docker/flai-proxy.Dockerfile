FROM python:3.12-slim

WORKDIR /app
COPY docker/flai_invocation_proxy.py /app/flai_invocation_proxy.py

EXPOSE 5001
CMD ["python3", "/app/flai_invocation_proxy.py"]
