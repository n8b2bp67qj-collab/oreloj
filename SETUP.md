# Oreloj — Pi Standalone Setup

Pi 3 A+, headless.  Hostname: `oreloj`, user: `oreloj`.
SSH: `ssh oreloj@oreloj.local`

---

## 1. Flash the SD card

Use **Raspberry Pi Imager** → **Raspberry Pi OS Lite (64-bit)**.
In the customisation panel (gear icon) set:

- Hostname: `oreloj`
- Username: `oreloj`
- WiFi SSID + password
- Enable SSH (password auth is fine)

> **Note:** this image uses cloud-init, not `firstrun.sh`.
> Settings live in `/boot/bootfs/user-data` if you need to edit them after flashing.
> `openssh-server` must be explicitly listed in the packages section — it is **not** installed by default.

---

## 2. First boot — install dependencies

```bash
ssh oreloj@oreloj.local

sudo apt update && sudo apt install -y \
    python3-pip \
    python3-evdev \
    mpv
```

No PipeWire or Bluetooth packages yet — audio is phase 2.

---

## 3. Add user to the input group

This lets globe.py grab the pen's evdev device without root:

```bash
sudo usermod -aG input oreloj
# Log out and back in for the group to take effect:
exit
ssh oreloj@oreloj.local
```

---

## 4. Copy project files

From your Mac:

```bash
cd ~/Documents/Claude/Projects/Web\ Radio\ Interactive\ Globe

scp globe.py stations.csv 99-globe-hid.rules oreloj@oreloj.local:~/
```

On the Pi:

```bash
mkdir -p ~/globe
mv ~/globe.py ~/stations.csv ~/globe/

sudo mv ~/99-globe-hid.rules /etc/udev/rules.d/
sudo udevadm control --reload-rules && sudo udevadm trigger
```

---

## 5. Test playback manually

Plug the pen USB into the Pi, then:

```bash
python3 ~/globe/globe.py
```

Tap a country — you should hear a stream within a few seconds on the 3.5mm jack.
Check logs with `journalctl --user -u globe -f` once the service is installed.

### Calibration (same as Mac)

```bash
python3 ~/globe/globe.py --calibrate
```

Tap countries and note any `⚠ NOT IN CODE_MAP` codes.
On Ctrl+C, an exit summary prints a ready-to-paste CODE_MAP snippet.

---

## 6. Install as a systemd user service

```bash
mkdir -p ~/.config/systemd/user
cp ~/globe.service ~/.config/systemd/user/

systemctl --user daemon-reload
systemctl --user enable globe
systemctl --user start globe

# Allow the service to run without a logged-in session:
sudo loginctl enable-linger oreloj
```

---

## 7. Audio — combined 3.5mm + Bluetooth sink  *(phase 2)*

> Come back here once the software layer is solid.

```bash
sudo apt install -y pipewire-audio bluez bluetooth

# Pair your Bluetooth speaker:
bluetoothctl
  power on
  agent on
  scan on
  # wait for your speaker's MAC, e.g. AA:BB:CC:DD:EE:FF
  pair   AA:BB:CC:DD:EE:FF
  trust  AA:BB:CC:DD:EE:FF
  connect AA:BB:CC:DD:EE:FF
  quit

# Then set BT_MAC in audio_setup.sh and run it:
bash ~/globe/audio_setup.sh AA:BB:CC:DD:EE:FF
```

Restart the service after audio is configured:
```bash
systemctl --user restart globe
```

---

## Useful commands

| What | Command |
|------|---------|
| Check status | `systemctl --user status globe` |
| Live logs | `journalctl --user -u globe -f` |
| Restart after editing | `systemctl --user restart globe` |
| Stop | `systemctl --user stop globe` |
| Check audio sinks | `pactl list short sinks` |
| Check pen is detected | `python3 -c "import evdev; print([d.name for d in map(evdev.InputDevice, evdev.list_devices())])"` |
