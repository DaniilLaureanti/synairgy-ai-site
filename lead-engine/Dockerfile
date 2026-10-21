FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PYTHONPATH=/app/src DATA_DIR=/app/data
WORKDIR /app
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt && useradd --create-home --uid 10001 engine
COPY src ./src
COPY config.json ./
RUN mkdir -p /app/data && chown engine:engine /app/data
USER engine
EXPOSE 8000
CMD ["python", "-m", "synairgy.cli", "serve", "--host", "0.0.0.0", "--port", "8000"]
