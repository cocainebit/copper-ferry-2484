#!/bin/sh
# Extra displays for a running desktop. Screen N (1-3) is X display :N with its own window manager,
# a full-control VNC stream on websocket port 6080+10N and a view-only stream on 6081+10N.
# Usage: screen.sh start N WIDTHxHEIGHT | screen.sh stop N | screen.sh status
set -eu

run_as_desktop() {
    runuser -u desktop -- sh -c "$1"
}

pids_file() {
    echo "/tmp/cubicle-screen-$1.pids"
}

stop_screen() {
    n=$1
    file=$(pids_file "$n")
    if [ -f "$file" ]; then
        # Only the processes this script started for this screen.
        for pid in $(cat "$file"); do
            kill "$pid" 2>/dev/null || true
        done
        rm -f "$file"
    fi
    rm -f "/tmp/.X${n}-lock" "/tmp/.X11-unix/X${n}"
}

case "${1:-}" in
start)
    n=${2:?screen number}
    geometry=${3:?WIDTHxHEIGHT}
    case "$n" in 1|2|3) ;; *) echo "screen must be 1-3" >&2; exit 2 ;; esac
    case "$geometry" in 1280x720|1440x900|1920x1080) ;; *) echo "unsupported geometry" >&2; exit 2 ;; esac
    [ -r /tmp/vnc-pass ] || { echo "primary desktop is not ready" >&2; exit 3; }
    stop_screen "$n"
    file=$(pids_file "$n")
    vnc=$((5900 + 10 * n))
    web=$((6080 + 10 * n))
    run_as_desktop "Xvfb :$n -screen 0 ${geometry}x24 -nolisten tcp > /tmp/xvfb-$n.log 2>&1 & echo \$!" >> "$file"
    for _ in 1 2 3 4 5 6 7 8 9 10; do
        [ -S "/tmp/.X11-unix/X$n" ] && break
        sleep 0.3
    done
    run_as_desktop "DISPLAY=:$n dbus-launch --exit-with-session xfwm4 --replace > /tmp/xfwm4-$n.log 2>&1 & echo \$!" >> "$file"
    run_as_desktop "DISPLAY=:$n xfdesktop > /tmp/xfdesktop-$n.log 2>&1 & echo \$!" >> "$file"
    run_as_desktop "x11vnc -display :$n -rfbauth /tmp/vnc-pass -forever -shared -rfbport $vnc -localhost > /tmp/vnc-$n.log 2>&1 & echo \$!" >> "$file"
    run_as_desktop "x11vnc -display :$n -rfbauth /tmp/vnc-pass -forever -shared -viewonly -rfbport $((vnc + 1)) -localhost > /tmp/vnc-ro-$n.log 2>&1 & echo \$!" >> "$file"
    run_as_desktop "websockify $web localhost:$vnc > /tmp/ws-$n.log 2>&1 & echo \$!" >> "$file"
    run_as_desktop "websockify $((web + 1)) localhost:$((vnc + 1)) > /tmp/ws-ro-$n.log 2>&1 & echo \$!" >> "$file"
    for _ in $(seq 1 30); do
        if python3 -c "import socket; socket.create_connection(('127.0.0.1', $web), 1).close()" 2>/dev/null; then
            actual=$(DISPLAY=:$n xdotool getdisplaygeometry | tr ' ' x)
            [ "$actual" = "$geometry" ] || { echo "geometry mismatch: $actual" >&2; exit 4; }
            echo "screen $n ready"
            exit 0
        fi
        sleep 0.5
    done
    echo "screen $n did not become ready" >&2
    exit 5
    ;;
stop)
    stop_screen "${2:?screen number}"
    echo "screen $2 stopped"
    ;;
status)
    for n in 1 2 3; do
        if [ -S "/tmp/.X11-unix/X$n" ]; then
            echo "$n=$(DISPLAY=:$n xdotool getdisplaygeometry | tr ' ' x)"
        fi
    done
    ;;
*)
    echo "usage: screen.sh start N WxH | stop N | status" >&2
    exit 2
    ;;
esac
