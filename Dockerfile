FROM node:22-alpine AS frontend
WORKDIR /app/frontend
RUN corepack enable
COPY frontend/package.json frontend/pnpm-lock.yaml frontend/pnpm-workspace.yaml ./
RUN pnpm install --frozen-lockfile
COPY frontend/ ./
RUN pnpm run build

FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1
WORKDIR /app
RUN useradd --create-home --uid 10001 seller
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt
COPY backend ./backend
COPY --from=frontend /app/frontend/dist ./frontend/dist
RUN mkdir -p /data && chown -R seller:seller /data /app
USER seller
EXPOSE 8087
CMD ["uvicorn", "backend.main:app", "--host", "0.0.0.0", "--port", "8087", "--proxy-headers", "--forwarded-allow-ips=*"]

