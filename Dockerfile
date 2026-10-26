FROM node:22-slim AS viewer
WORKDIR /viewer
COPY viewer/package.json viewer/package-lock.json ./
RUN npm ci
COPY viewer/ ./
RUN npm run build

FROM python:3.12-slim
WORKDIR /app
COPY pyproject.toml requirements.lock ./
COPY src ./src
RUN pip install --no-cache-dir -r requirements.lock && pip install --no-cache-dir --no-deps . \
    && useradd --create-home appuser && mkdir /data && chown appuser /data
COPY --from=viewer /viewer/dist ./viewer/dist
USER appuser
ENV RAG_DATA_DIR=/data
VOLUME ["/data"]
EXPOSE 8000
CMD ["uvicorn", "rag_pre_ingest.main:app", "--host", "0.0.0.0", "--port", "8000"]
