FROM node:20-alpine AS frontend-build
WORKDIR /frontend
COPY frontend/package.json ./
RUN npm install
COPY frontend/ ./
RUN npm run build

FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /srv/hrms

RUN apt-get update \
    && apt-get install -y --no-install-recommends build-essential curl \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt ./
RUN pip install -r requirements.txt

COPY app ./app
COPY sql ./sql
COPY scripts ./scripts
COPY templates ./templates
COPY static ./static
COPY deployment ./deployment
COPY README.md ./

COPY --from=frontend-build /frontend/dist ./static/dashboard

EXPOSE 8000

CMD ["bash", "-lc", "python scripts/init_db.py && uvicorn app.main:app --host 0.0.0.0 --port 8000"]
