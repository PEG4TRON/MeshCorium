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
    dbus \
    ca-certificates \
    tzdata

WORKDIR /opt/meshcorium

COPY requirements.txt /opt/meshcorium/requirements.txt
RUN python3 -m venv /opt/meshcorium/.venv \
 && /opt/meshcorium/.venv/bin/pip install --no-cache-dir --upgrade pip \
 && /opt/meshcorium/.venv/bin/pip install --no-cache-dir -r /opt/meshcorium/requirements.txt

COPY CHANGELOG.md LICENSE README.md README_EN.md README_RU.md .meshcorium_version /opt/meshcorium/
COPY meshcorium/ /opt/meshcorium/meshcorium/
COPY icons /opt/meshcorium/icons
COPY sounds /opt/meshcorium/sounds
COPY vendor /opt/meshcorium/vendor
COPY other /opt/meshcorium/other
COPY defaults /opt/meshcorium/defaults
COPY --from=web-build /src/web/dist /opt/meshcorium/web/dist
COPY web/attachments /opt/meshcorium/web/attachments
COPY wiki /opt/meshcorium/wiki
COPY docker/docker-entrypoint.sh /usr/local/bin/meshcorium-entrypoint

RUN chmod +x /usr/local/bin/meshcorium-entrypoint \
 && mkdir -p /etc/meshcorium /var/lib/meshcorium /var/log/meshcorium

ENV PYTHONUNBUFFERED=1
ENV MESHCORIUM_HOST=0.0.0.0
ENV MESHCORIUM_PORT=8080
ENV MESHCORIUM_CONFIG_DIR=/etc/meshcorium
ENV MESHCORIUM_DATA_DIR=/var/lib/meshcorium
ENV MESHCORIUM_LOG_DIR=/var/log/meshcorium
ENV DBUS_SYSTEM_BUS_ADDRESS=unix:path=/run/dbus/system_bus_socket

EXPOSE 8080

ENTRYPOINT ["meshcorium-entrypoint"]
