FROM python:3.11-slim

WORKDIR /app

# Default port (can be overridden)
ARG BACKEND_PORT=8000
ENV BACKEND_PORT=${BACKEND_PORT}

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY alembic.ini .
COPY alembic/ ./alembic/
COPY app/ ./app/

EXPOSE ${BACKEND_PORT}

CMD sh -c "uvicorn app.main:app --host 0.0.0.0 --port ${BACKEND_PORT}"
