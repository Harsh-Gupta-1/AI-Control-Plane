FROM ubuntu:22.04

# Install python and playwright (basic headless chromium only)
RUN apt-get update && apt-get install -y python3 python3-pip wget curl && \
    pip3 install playwright beautifulsoup4 && \
    playwright install chromium --with-deps && \
    apt-get clean && rm -rf /var/lib/apt/lists/*

# Set up sandbox directories
RUN mkdir -p /workspace /downloads /input /output /temp
WORKDIR /workspace
