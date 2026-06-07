# Stage 1: build React frontend
FROM node:20-alpine AS frontend-builder

WORKDIR /frontend
COPY frontend/package*.json ./
RUN npm install
COPY frontend ./
RUN npm run build

# Stage 2: Python runtime
FROM python:3.11-slim

WORKDIR /app

RUN apt-get update \
    && apt-get install -y --no-install-recommends supervisor \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

RUN mkdir -p log data conf frontend/dist

COPY biz ./biz
COPY fonts ./fonts
COPY api.py ./api.py
COPY conf/prompt_templates.yml ./conf/prompt_templates.yml
COPY deployment/supervisord.conf /etc/supervisor/conf.d/supervisord.conf
COPY --from=frontend-builder /frontend/dist ./frontend/dist

EXPOSE 5001

CMD ["/usr/bin/supervisord", "-c", "/etc/supervisor/conf.d/supervisord.conf"]
