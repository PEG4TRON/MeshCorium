FROM alpine:latest AS web-build

RUN apk add --no-cache nodejs npm

WORKDIR /src

COPY web/package*.json /src/web/
RUN cd /src/web && npm ci

COPY web /src/web
RUN cd /src/web && npm run build


FROM alpine:latest

RUN apk add --no-cache \
    python3 \
    py3-pip \
    py3-virtualenv \
    bluez \
    ca-certificates \
    tzdata

WORKDIR /opt/meshcorium

COPY requirements.txt /opt/meshcorium/requirements.txt
RUN python3 -m venv /opt/meshcorium/.venv \
 && /opt/meshcorium/.venv/bin/pip install --no-cache-dir --upgrade pip \
 && /opt/meshcorium/.venv/bin/pip install --no-cache-dir -r /opt/meshcorium/requirements.txt

COPY CHANGELOG.md LICENSE README.md README_EN.md README_RU.md /opt/meshcorium/
COPY contact_admin.py contact_backend.py contact_groups.py contact_service.py contact_store.py mobile_push.py /opt/meshcorium/
COPY meshcorium_ble_transport.py meshcorium_client.py meshcorium_serial_legacy.py meshcorium_serial_transport.py meshcorium_transport.py meshcorium_web.py /opt/meshcorium/
COPY icons /opt/meshcorium/icons
COPY sounds /opt/meshcorium/sounds
COPY vendor /opt/meshcorium/vendor
COPY other /opt/meshcorium/other
COPY defaults /opt/meshcorium/defaults
COPY --from=web-build /src/web/dist /opt/meshcorium/web/dist
COPY docker/docker-entrypoint.sh /usr/local/bin/meshcorium-entrypoint

RUN chmod +x /usr/local/bin/meshcorium-entrypoint \
 && mkdir -p /etc/meshcorium /var/lib/meshcorium /var/log/meshcorium

ENV PYTHONUNBUFFERED=1
ENV MESHCORIUM_HOST=0.0.0.0
ENV MESHCORIUM_PORT=8080
ENV MESHCORIUM_CONFIG_DIR=/etc/meshcorium
ENV MESHCORIUM_DATA_DIR=/var/lib/meshcorium
ENV MESHCORIUM_LOG_DIR=/var/log/meshcorium

EXPOSE 8080

ENTRYPOINT ["meshcorium-entrypoint"]

