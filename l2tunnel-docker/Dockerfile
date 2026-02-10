FROM python:3.11-alpine

RUN apk add --no-cache libpcap-dev gcc musl-dev make git ethtool

WORKDIR /app
RUN git clone --depth 1 https://github.com/mborgerson/l2tunnel.git . && make

COPY entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

ENTRYPOINT ["/entrypoint.sh"]
