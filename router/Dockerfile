FROM python:3.11-slim

WORKDIR /app
COPY llm_router.py /app/llm_router.py
RUN mkdir -p /app/state

EXPOSE 5002
CMD ["python", "-u", "/app/llm_router.py"]
