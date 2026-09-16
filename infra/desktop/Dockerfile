FROM debian:bookworm-slim
ENV DEBIAN_FRONTEND=noninteractive DISPLAY=:0 HOME=/home/desktop LANG=C.UTF-8
RUN apt-get update && apt-get install -y --no-install-recommends python3 python3-pip python3-venv python3-websockify xvfb x11vnc xfce4 xfce4-terminal dbus-x11 novnc chromium xdotool scrot xclip fonts-dejavu ca-certificates curl sudo && rm -rf /var/lib/apt/lists/*
RUN python3 -m venv /opt/tools && /opt/tools/bin/pip install --no-cache-dir playwright==1.55.0
RUN groupadd -g 1000 desktop && useradd -m -u 1000 -g 1000 -G audio,video desktop && mkdir -p /tmp/.X11-unix && chmod 1777 /tmp/.X11-unix
COPY start.sh tools.py wallpaper.svg /opt/desktop/
RUN chmod +x /opt/desktop/start.sh && mkdir -p /opt/desktop/defaults && chown -R desktop:desktop /home/desktop
USER desktop
WORKDIR /home/desktop
CMD ["/opt/desktop/start.sh"]
