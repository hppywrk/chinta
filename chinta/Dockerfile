FROM python:3.12-slim

WORKDIR /workspace

COPY packages/chinta_observability packages/chinta_observability
COPY chinta chinta
WORKDIR /workspace/chinta
RUN pip install --no-cache-dir -r requirements.txt
ENV CHINTA_BACKEND_PORT=8080

EXPOSE 8080

CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "8080"]
