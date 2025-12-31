FROM ubuntu:22.04

ENV DEBIAN_FRONTEND=noninteractive

# Install ffmpeg, python3.10, pip and tools
RUN apt-get update && apt-get install -y \
    python3.10 \
    python3-pip \
    ffmpeg \
    procps \
    ca-certificates \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Copy requirements first for efficient caching
COPY requirements.txt /app/requirements.txt
RUN pip3 install --no-cache-dir -r /app/requirements.txt

# Copy the application
COPY . /app

# Ensure videos directory exists inside container and provide placeholder files
RUN mkdir -p /app/videos && touch /app/stream.log /app/playlist.txt || true

# Add healthcheck script and make executable
RUN chmod +x /app/healthcheck.sh || true

EXPOSE 8501

# Use a simple entry that runs Streamlit. Streamlit runs as PID 1 in container.
HEALTHCHECK --interval=30s --timeout=10s --start-period=10s --retries=3 \
    CMD ["/app/healthcheck.sh"]

CMD ["streamlit", "run", "app.py", "--server.port", "8501", "--server.address", "0.0.0.0"]
