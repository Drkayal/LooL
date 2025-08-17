FROM python:3.10-slim

ENV PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1

RUN apt-get update \
 && apt-get install -y --no-install-recommends ffmpeg git curl \
 && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY requirements.txt .

# Install dependencies (py-tgcalls pinned in requirements.txt)
RUN pip install --upgrade pip \
 && pip install -r requirements.txt

COPY . .

CMD ["bash", "start"]
