FROM python:3.12-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY plant_service plant_service
COPY simulator simulator
RUN useradd --uid 10001 --create-home plant
USER plant
CMD ["sh", "-c", "uvicorn plant_service.app:app --host 0.0.0.0 --port ${PORT:-8080}"]
