FROM python:3.12-slim

WORKDIR /workspace

COPY packages/chinta_observability packages/chinta_observability
COPY chinta-platform chinta-platform
WORKDIR /workspace/chinta-platform
RUN pip install --no-cache-dir -r requirements.txt
ENV CHINTA_PLATFORM_PORT=8085

EXPOSE 8085

CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "8085"]
