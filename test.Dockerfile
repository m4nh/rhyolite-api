FROM python:3.12-slim

WORKDIR /app

# Needed because testing.sh uses bash features.
RUN apt-get update \
    && apt-get install -y --no-install-recommends bash ca-certificates \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY testing.py testing.sh ./
RUN chmod +x ./testing.sh

# Runtime configuration for testing.
#
# You must provide:
# - API_HOST (e.g. http://rhyolite-api:8000 or rhyolite-api:8000)
ENV API_HOST=

CMD ["bash", "-lc", "./testing.sh"]
