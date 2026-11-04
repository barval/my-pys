FROM debian:bookworm-slim

ENV DEBIAN_FRONTEND=noninteractive

RUN apt-get update \
 && apt-get install -y --no-install-recommends \
    ca-certificates \
    curl \
    dnsmasq \
    dnsutils \
    iproute2 \
    openssl \
    procps \
    python3 \
 && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY vendor/lite-kit/ /app/
RUN chmod +x /app/start.sh /app/stop.sh /app/check.sh /app/install-firmware.sh

# run/downgrade makes the stand offer the .46 image to the factory build.
CMD ["sh", "-c", "mkdir -p /app/run /app/log && touch /app/run/downgrade && ./start.sh && tail -f /dev/null"]
