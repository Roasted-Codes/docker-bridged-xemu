# syntax=docker/dockerfile:1

FROM lscr.io/linuxserver/xemu:latest

# set version label
LABEL maintainer="Roasted-Codes"

# Install additional packages for window automation and networking
RUN \
  apt-get update && \
  apt-get install -y --no-install-recommends \
    wmctrl \
    ethtool && \
  apt-get autoclean && \
  rm -rf \
    /var/lib/apt/lists/* \
    /var/tmp/* \
    /tmp/*

# Replace upstream autostart with custom version
COPY root/defaults/autostart /defaults/autostart
