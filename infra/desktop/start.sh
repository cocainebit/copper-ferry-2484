#!/bin/sh
set -eu
if [ "$(id -u)" = 0 ]; then
    chown desktop:desktop /home/desktop
    rm -f /tmp/.X0-lock /tmp/.X11-unix/X0
    exec runuser -u desktop -- /opt/desktop/start.sh
fi
if [ "${DESKTOP_DBUS_SESSION:-}" != 1 ]; then
    export DESKTOP_DBUS_SESSION=1
    exec dbus-run-session -- /opt/desktop/start.sh
fi
: "${VNC_PASSWORD:?VNC_PASSWORD is required}"
mkdir -p "$HOME/.config" "$HOME/Desktop" "$HOME/Downloads"
# A persistent profile can contain stale singleton locks after a crash.
find "$HOME/.config/chromium" -maxdepth 1 -name 'Singleton*' -type l -delete 2>/dev/null || true
DESKTOP_RESOLUTION=${DESKTOP_RESOLUTION:-1440x900}
case "$DESKTOP_RESOLUTION" in
    1280x720|1440x900|1920x1080) ;;
    *) echo "Unsupported desktop resolution" >&2; exit 1 ;;
esac
Xvfb :0 -screen 0 "${DESKTOP_RESOLUTION}x24" -nolisten tcp &
sleep 1
startxfce4 > /tmp/xfce.log 2>&1 &
sleep 2
if [ ! -f "$HOME/.config/desktop-initialized" ]; then
xfconf-query -c xsettings -p /Net/ThemeName -s Adwaita-dark || true
xfconf-query -c xfce4-desktop -p /backdrop/screen0/monitor0/workspace0/last-image --create -t string -s /opt/desktop/wallpaper.svg || true
touch "$HOME/.config/desktop-initialized"
fi
# VNC password files avoid exposing the password in process arguments.
x11vnc -storepasswd "$VNC_PASSWORD" /tmp/vnc-pass >/dev/null
chmod 600 /tmp/vnc-pass
x11vnc -display :0 -rfbauth /tmp/vnc-pass -forever -shared -rfbport 5900 -localhost > /tmp/vnc.log 2>&1 &
x11vnc -display :0 -rfbauth /tmp/vnc-pass -forever -shared -viewonly -rfbport 5901 -localhost > /tmp/vnc-readonly.log 2>&1 &
websockify 6080 localhost:5900 > /tmp/ws.log 2>&1 &
websockify 6081 localhost:5901 > /tmp/ws-readonly.log 2>&1 &
# Only available inside this sandbox; never publish CDP directly to users.
# Docker Desktop development cannot provide Chromium's namespace sandbox.
# Production leaves this unset and requires a compatible hardened runtime.
chromium ${CHROMIUM_DEV_FLAGS:-} --disable-dev-shm-usage --remote-debugging-address=127.0.0.1 --remote-debugging-port=9222 --user-data-dir="$HOME/.config/chromium" --no-first-run about:blank > /tmp/chromium.log 2>&1 &
wait
