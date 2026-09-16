#!/bin/sh
set -eu
: "${VNC_PASSWORD:?VNC_PASSWORD is required}"
mkdir -p "$HOME/.config" "$HOME/Desktop" "$HOME/Downloads"
# A persistent profile can contain stale singleton locks after a crash.
find "$HOME/.config/chromium" -maxdepth 1 -name 'Singleton*' -type l -delete 2>/dev/null || true
Xvfb :0 -screen 0 1440x900x24 -nolisten tcp &
sleep 1
dbus-launch startxfce4 > /tmp/xfce.log 2>&1 &
sleep 2
xfconf-query -c xsettings -p /Net/ThemeName -s Adwaita-dark || true
xfconf-query -c xfce4-desktop -p /backdrop/screen0/monitor0/workspace0/last-image --create -t string -s /opt/desktop/wallpaper.svg || true
# VNC password files avoid exposing the password in process arguments.
x11vnc -storepasswd "$VNC_PASSWORD" /tmp/vnc-pass >/dev/null
chmod 600 /tmp/vnc-pass
x11vnc -display :0 -rfbauth /tmp/vnc-pass -forever -shared -rfbport 5900 -localhost > /tmp/vnc.log 2>&1 &
x11vnc -display :0 -rfbauth /tmp/vnc-pass -forever -shared -viewonly -rfbport 5901 -localhost > /tmp/vnc-readonly.log 2>&1 &
websockify 6080 localhost:5900 > /tmp/ws.log 2>&1 &
websockify 6081 localhost:5901 > /tmp/ws-readonly.log 2>&1 &
# Only available inside this sandbox; never publish CDP directly to users.
chromium --disable-dev-shm-usage --remote-debugging-address=127.0.0.1 --remote-debugging-port=9222 --user-data-dir="$HOME/.config/chromium" --no-first-run about:blank > /tmp/chromium.log 2>&1 &
wait
