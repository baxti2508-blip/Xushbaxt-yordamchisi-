FROM python:3.12-slim
RUN apt-get update && apt-get install -y --no-install-recommends ffmpeg ca-certificates gosu && rm -rf /var/lib/apt/lists/*
WORKDIR /app
COPY bot.py baseline.json ./
RUN useradd --create-home bot && mkdir /data && chown bot:bot /data
ENV DATA_DIR=/data PYTHONUNBUFFERED=1
VOLUME ["/data"]
ENTRYPOINT ["sh", "-c", "mkdir -p \"$DATA_DIR\" && chown -R bot:bot \"$DATA_DIR\" && exec gosu bot python /app/bot.py"]
