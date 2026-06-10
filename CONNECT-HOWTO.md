# Oreloj — connecting at a new place (Wi-Fi + Bluetooth)

Short owner's guide, written 2026-06-10. Current device state: Raspberry Pi OS
Trixie, cloud-init + NetworkManager, instance-id suffix `-net5` in `cmdline.txt`.

---

## Wi-Fi — two ways

### Way 1 (best): add the network BEFORE you move the globe

While the globe is still online at the current place:

1. Open **http://oreloj.local:5000 → Wi-Fi panel**, add the new place's
   network name + password. *(Or ask Claude to pre-add it over SSH.)*
2. That's it — at the new place the Pi joins by itself within ~2 minutes of
   power-on. `oreloj.local:5000` works once your laptop is on the same wifi.

### Way 2 (fallback): the SD card method — when the globe is already offline

1. Unplug the Pi, take out the SD card, put it in the Mac. Wait for
   **"bootfs"** to appear in Finder (if it doesn't, re-seat the card).
2. Open the file `network-config` on bootfs. Under `access-points:` add the
   new network **below the existing ones**, exactly like this (2-space
   indentation matters):

   ```yaml
         access-points:
           "Existing Network":
             password: "..."
           "NEW NETWORK NAME":
             password: "NEW PASSWORD"
   ```

   ⚠️ The network name must match **character for character** — capitals,
   accents, and even spaces at the end (the "Freebox Bestron " incident: its
   real name ends with an invisible space). On a Mac on that wifi, the exact
   name shows in System Settings → Wi-Fi, or via
   `networksetup -listpreferredwirelessnetworks en0`.

3. Open `cmdline.txt` (one long line). Find `i=rpi-imager-1778777569304-net5`
   and bump the suffix: `-net5` → `-net6` (any new value works; this is what
   makes the Pi re-read the wifi config — without it, edits are ignored).
4. Eject the card properly (Finder ⏏), back into the Pi, power on, wait
   3 minutes. The globe appears at `oreloj.local:5000`.
5. If SSH complains "REMOTE HOST IDENTIFICATION HAS CHANGED" afterwards:
   `ssh-keygen -R oreloj.local` and reconnect — expected after this method.

*Easiest of all: put the SD card in the Mac and ask Claude
"add wifi <name> / <password>" — these edits are fiddly by hand.*

---

## Bluetooth speaker

1. **Phones first:** turn Bluetooth OFF on all phones nearby — speakers
   latch onto the last phone they saw and hijack the pairing window.
2. **If the speaker has met many devices** (or pairing keeps un-pairing
   itself): wipe its device list. On a Bose SoundLink III: hold the
   Bluetooth button **a full 10 seconds, past the blinking, until a voice
   prompt confirms the list was cleared.** No voice prompt = not wiped.
3. The speaker should now blink blue (pairing mode).
4. Open **http://oreloj.local:5000 → Bluetooth → Scan**, then **Pair** next
   to the speaker. The UI verifies the pairing for real and wires the
   speaker into the globe's audio automatically.
5. Done. From then on the Pi reconnects the speaker **by itself within
   2 minutes** whenever it's on and in range — just switch the speaker on.

### If the globe seems dead (taps register, no sound)

It is almost never a crash — it's the speaker link. The globe keeps playing
into the empty headphone jack, which is silent. Check the Bluetooth panel:
if the speaker isn't connected, switch it on and wait 2 minutes, or redo
step 2–4. **Plan B that always works: a 3.5 mm aux cable from the Pi's jack
to the speaker's AUX input — no Bluetooth involved at all.**
