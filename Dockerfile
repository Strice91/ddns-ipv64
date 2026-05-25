FROM python:3.13-alpine

ARG BUILD_DATE
LABEL maintainer="alcapone1933 alcapone1933@cosanostra-cloud.de" \
      org.opencontainers.image.created="$BUILD_DATE" \
      org.opencontainers.image.authors="alcapone1933 alcapone1933@cosanostra-cloud.de" \
      org.opencontainers.image.url="https://hub.docker.com/r/alcapone1933/ddns-ipv64" \
      org.opencontainers.image.version="v2.0.0" \
      org.opencontainers.image.ref.name="alcapone1933/ddns-ipv64" \
      org.opencontainers.image.title="DDNS Updater ipv64.net" \
      org.opencontainers.image.description="Community DDNS Updater fuer ipv64.net (Python Rewrite)"

ENV TZ=Europe/Berlin \
    CRON_TIME="*/15 * * * *" \
    CRON_TIME_DIG="*/30 * * * *" \
    VERSION="v2.0.0" \
    CURL_USER_AGENT="docker-ddns-ipv64-python/version=v2.0.0 github.com/Strice91/ddns-ipv64" \
    NOTIFY_URL="" \
    NOTIFY_SKIP_TEST="no" \
    IP_CHECK="yes" \
    NAME_SERVER="ns1.ipv64.net" \
    NETWORK_CHECK="yes" \
    PUID="0" \
    PGID="0"

RUN apk add --update --no-cache tzdata tini && \
    rm -rf /var/cache/apk/*

RUN mkdir -p /data/log /app /etc/cron.d/ && \
    touch /etc/.firstrun

COPY app/requirements.txt /app/
RUN pip install --no-cache-dir -r /app/requirements.txt

COPY app/ /app/

WORKDIR /data
ENTRYPOINT ["/sbin/tini", "--", "python3", "/app/entrypoint.py"]
HEALTHCHECK --interval=1500s --timeout=30s --start-period=5s --retries=2 CMD python3 /app/healthcheck.py
