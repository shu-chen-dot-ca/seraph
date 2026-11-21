#!/usr/bin/env bash
# Runs the live copy: the release installed in ~/seraph (deploy/install.sh), on your data, VMs and agents, at
# http://localhost:8001. It shows the app's log here; Ctrl+C stops it. Nothing starts
# it otherwise, not even a reboot.
#
# It runs as the user service seraph (deploy/seraph.service), so Update in the app can switch it to a new release
# while it runs (deploy/switch.sh). ~/seraph/stopped tells switch.sh you stopped it, so it never starts it again.
# ./run.sh (your working code) uses the same data, VMs and port: only one of the two runs at a time, so this closes
# ./run.sh, another ./live.sh and anything else on the port before it starts.
cd "$(dirname "$0")"
LIVE="$HOME/seraph"
PORT=$(grep '^BACKEND_PORT=' .env | cut -d= -f2)

if [[ ! -L "$LIVE/current" ]]; then
    echo "There is no live copy yet: deploy/install.sh <tag> makes it."
    exit 1
fi

# Every other instance closes first, so this one takes over.
# Another ./live.sh: it shows the log with journalctl, so the script is that journalctl's parent. It has to go, or
# its Ctrl+C would stop the live copy started here. It stops the live copy itself as it exits.
# Only a journalctl whose parent runs live.sh: never a shell or a command that only mentions it.
for TAIL in $(pgrep -x journalctl); do
    OLD=$(ps -o ppid= -p "$TAIL" | tr -d ' ')
    if [[ "$(ps -o args= -p "$OLD")" != *live.sh ]]; then
        continue
    fi
    echo "Closing the other ./live.sh ($OLD)..."
    kill "$OLD" "$TAIL" 2>/dev/null
    while kill -0 "$OLD" 2>/dev/null; do
        sleep 1
    done
done

# The live copy without a ./live.sh (Update in the app started it, or its terminal went away).
if systemctl --user is-active --quiet seraph; then
    echo "Stopping the live copy that runs already..."
    systemctl --user stop seraph
fi

# ./run.sh or anything else on the port. When its backend goes, ./run.sh closes its Vite too.
LEFT=$(lsof -t -iTCP:"$PORT" -sTCP:LISTEN)
if [[ -n "$LEFT" ]]; then
    echo "Closing what runs on port $PORT:" $LEFT
    kill $LEFT 2>/dev/null
    sleep 2
    kill -9 $LEFT 2>/dev/null
fi

rm -f "$LIVE/stopped"
systemctl --user start seraph
echo "Seraph $(cat "$LIVE/current/VERSION") runs at http://localhost:$PORT. Ctrl+C stops it."

trap 'touch "$LIVE/stopped"; echo "Stopping..."; systemctl --user stop seraph' EXIT
trap 'exit' INT TERM HUP
journalctl --user -u seraph -f -n 0 --output=cat
