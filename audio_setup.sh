#!/usr/bin/env bash
# Globe Radio — PulseAudio/PipeWire combined sink setup
# Usage: ./audio_setup.sh [BT_MAC]
# Creates a combined sink (globe_out) routing to 3.5mm jack + optional Bluetooth.

BT_MAC="${1:-}"
set -euo pipefail
log() { echo "▸ $*"; }

log "Waiting for audio server…"
for i in $(seq 1 10); do pactl info &>/dev/null && break; sleep 1; done
pactl info &>/dev/null || { echo "ERROR: audio server not running"; exit 1; }
log "Audio server ready"

BUILTIN_SINK=$(pactl list short sinks \
    | grep -E "bcm2835|analog-stereo|headphones" | head -1 | awk '{print $2}')
if [[ -z "$BUILTIN_SINK" ]]; then
    log "WARNING: built-in sink not found — listing sinks:"; pactl list short sinks
    BUILTIN_SINK="alsa_output.platform-bcm2835_audio.stereo-fallback"
fi
log "Built-in sink: $BUILTIN_SINK"
amixer -q cset numid=3 1 2>/dev/null || true  # force 3.5mm (not HDMI)

BT_SINK=""
if [[ -n "$BT_MAC" ]]; then
    log "Connecting Bluetooth: $BT_MAC"
    bluetoothctl connect "$BT_MAC" &
    BT_PID=$!
    for i in $(seq 1 10); do
        sleep 1
        BT_SINK=$(pactl list short sinks | grep -i "bluez\|bluetooth" | head -1 | awk '{print $2}')
        [[ -n "$BT_SINK" ]] && break
    done
    wait "$BT_PID" 2>/dev/null || true
    [[ -n "$BT_SINK" ]] && log "Bluetooth sink: $BT_SINK" || log "WARNING: Bluetooth sink not found"
fi

pactl unload-module module-combine-sink 2>/dev/null || true
SLAVES="${BT_SINK:+$BUILTIN_SINK,$BT_SINK}"
SLAVES="${SLAVES:-$BUILTIN_SINK}"
[[ -n "$BT_SINK" ]] && log "Combined sink: 3.5mm + Bluetooth" || log "Sink: 3.5mm only"

pactl load-module module-combine-sink sink_name=globe_out slaves="$SLAVES" \
    sink_properties=device.description=Globe-Radio > /dev/null
pactl set-default-sink globe_out
pactl set-sink-volume globe_out 80%
log "Default sink → globe_out @ 80% ✓"
