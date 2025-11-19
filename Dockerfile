# === Base image: slim Python runtime ===
FROM python:3.12-slim AS base

# Prevent Python from writing .pyc files and buffering stdout/stderr
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

# Install system dependencies (for psycopg2 and friends)
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    libpq-dev \
    && rm -rf /var/lib/apt/lists/*

# Set work directory
WORKDIR /app

# === Install Python dependencies ===
# Copy only requirements first to leverage Docker cache
COPY requirements.txt /app/

RUN pip install --no-cache-dir -r requirements.txt

# === Application code ===
COPY . /app

# Create a non-root user and switch to it
RUN useradd -m appuser && chown -R appuser /app
USER appuser

# Expose port for Gunicorn
EXPOSE 8000

# Environment (you can override these at runtime)
# Flask should run in production mode inside the container
ENV FLASK_ENV=production

# Gunicorn configuration:
# - 4 worker processes
# - gthread worker class (good for simple apps)
# - Bind to all interfaces on port 8000
CMD ["gunicorn", "-w", "4", "-k", "gthread", "-b", "0.0.0.0:8000", "app:app"]
