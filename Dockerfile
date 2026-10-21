FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY hello.py index.html ./

RUN useradd --system --no-create-home appuser
USER appuser

EXPOSE 8000
CMD ["sh", "-c", "exec gunicorn hello:application --bind 0.0.0.0:${PORT:-8000} --worker-class gthread --workers 2 --threads 4 --timeout 120 --access-logfile - --error-logfile -"]
