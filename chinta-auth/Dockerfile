FROM python:3.12-slim

WORKDIR /workspace

COPY packages/chinta_observability packages/chinta_observability
COPY chinta-auth chinta-auth
WORKDIR /workspace/chinta-auth
RUN pip install --no-cache-dir -r requirements.txt
ENV PORT=8083

EXPOSE 8083

CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "8083"]
