FROM python:3.11-slim

WORKDIR /app

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

RUN pip install --no-cache-dir fastapi==0.116.1 uvicorn==0.35.0 requests==2.32.5 python-dotenv==1.1.1

COPY app ./app
COPY config ./config
COPY .env.example ./.env.example

EXPOSE 8090

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8090"]
