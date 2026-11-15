# Quran Voice Bot — Docker image with Python + ffmpeg (for Render or any Docker host).
FROM python:3.12-slim

RUN apt-get update \
    && apt-get install -y --no-install-recommends ffmpeg libopus0 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY bot.py .

# Token comes from the DISCORD_TOKEN environment variable (set it in the host's dashboard).
CMD ["python", "bot.py"]
