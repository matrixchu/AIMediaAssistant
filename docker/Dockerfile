FROM python:3.11-slim

ENV PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PYTHONPATH=/app/src

WORKDIR /app

# Install dependencies first for better layer caching.
COPY requirements.txt ./
RUN pip install --upgrade pip && pip install -r requirements.txt

# Copy the project.
COPY pyproject.toml ./
COPY src ./src

EXPOSE 8000

CMD ["uvicorn", "ai_media_assistant.api.app:app", "--host", "0.0.0.0", "--port", "8000"]
