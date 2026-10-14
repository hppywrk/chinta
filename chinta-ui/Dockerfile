FROM python:3.12-slim

WORKDIR /workspace

COPY packages/chinta_observability packages/chinta_observability
COPY chinta-ui chinta-ui
WORKDIR /workspace/chinta-ui
RUN pip install --no-cache-dir -r requirements.txt
ENV CHINTA_UI_PORT=8086

EXPOSE 8086

CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "8086"]
