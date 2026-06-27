FROM python:3.11-slim

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

RUN mkdir -p instance data/imports

ENV FLASK_APP=app.py
ENV FLASK_ENV=production
ENV SECRET_KEY=change-me-in-production

EXPOSE 5200

CMD ["python", "app.py"]
