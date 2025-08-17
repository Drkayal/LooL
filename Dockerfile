FROM python:3.10-slim

ENV PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1

RUN apt-get update \
 && apt-get install -y --no-install-recommends ffmpeg git curl \
 && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY requirements.txt .

# Install voice-calls stack first to avoid dependency conflicts
RUN pip install --upgrade pip \
 && pip install --pre tgcalls==3.0.0.dev6 \
 && pip install --no-deps pytgcalls==2.1.0 \
 && pip install -r requirements.txt

COPY . .

CMD ["bash", "start"]
