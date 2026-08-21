FROM ubuntu:22.04

# Option B (MVP-appropriate): Lightweight approach avoiding Playwright/Chromium installation.
# This minimizes build time, complexity, and image size.
RUN apt-get update && apt-get install -y python3 python3-pip wget curl && \
    apt-get clean

# Set up sandbox directories
RUN mkdir -p /workspace /downloads /input /output /temp
WORKDIR /workspace
