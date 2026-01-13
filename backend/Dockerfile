FROM python:3.11-slim

WORKDIR /app

# Default port (can be overridden)
ARG BACKEND_PORT=8000
ENV BACKEND_PORT=${BACKEND_PORT}

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app/ ./app/

EXPOSE ${BACKEND_PORT}

CMD uvicorn app.main:app --host 0.0.0.0 --port ${BACKEND_PORT}
