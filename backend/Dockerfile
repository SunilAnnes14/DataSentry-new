# Build context: repository root (needs the compiled contract artifact)
FROM node:22-slim AS contracts
WORKDIR /bc
COPY blockchain/package*.json ./
RUN npm ci
COPY blockchain/ ./
RUN npx hardhat compile

FROM python:3.11-slim
WORKDIR /app/backend
COPY backend/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY backend/ .
COPY --from=contracts /bc/artifacts /app/blockchain/artifacts
EXPOSE 8000
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
