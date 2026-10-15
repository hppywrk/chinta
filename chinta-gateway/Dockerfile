FROM python:3.12-slim

WORKDIR /workspace

COPY packages/chinta_observability packages/chinta_observability
COPY chinta-gateway chinta-gateway
WORKDIR /workspace/chinta-gateway
RUN pip install --no-cache-dir -r requirements.txt

ENV CHINTA_GATEWAY_PORT=8084

EXPOSE 8084

CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "8084"]
