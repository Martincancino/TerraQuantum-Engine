FROM python:3.11-slim

RUN apt-get update && apt-get install -y \
    build-essential gcc g++ python3-dev \
    && rm -rf /var/lib/apt/lists/* \
    && addgroup --system tq && adduser --system --ingroup tq tq

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

RUN chown -R tq:tq /app

USER tq

EXPOSE 8010

CMD ["sh", "-c", "python -m uvicorn main:app --host ${TERRAQUANTUM_HOST:-0.0.0.0} --port ${TERRAQUANTUM_PORT:-8010}"]
