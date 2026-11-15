# Discord Voice — Quran Bot

A small Discord bot that plays Quran recitation in a voice channel, 24/7.
It streams **direct MP3 files from mp3quran.net** — no YouTube, no login, no verification blocks.

- Never joins by itself after a restart. A staff member joins the ONE fixed voice channel first and runs `/start`; the bot then joins and plays surah 001 → 114 in order, then loops. (Joining an empty channel leaves the bot outside Discord's voice-encryption group and its audio is silently dropped, so a listener must be present at the first join.) After that first start, it auto-rejoins by itself whenever disconnected. Restarts wait for `/start` again and begin from Surah 1.
- Commands (slash + typed versions of each):
  - `/play <number>` or `!play 50` — anyone can request a surah; it is queued and plays after the current surah. When the request line empties, the main sequence resumes where it left off (25 → 50 requested → back to 26). Max 3 queued requests per person.
  - `/start` or `!start` — staff only (Administrator / Manage Server). Already online → says so; disconnected → rejoins; cannot join → "maintenance".
  - `/now` or `!now` — shows the surah playing now (number + name) and the request line.
  - There is **no stop command** — by design, nobody can stop the recitation.
  - A watchdog rejoins the channel by itself if the bot is ever disconnected.
- The fixed channel is set in `bot.py` (`FIXED_VOICE_CHANNEL_ID`, or the `VOICE_CHANNEL_ID` env var).
- Built for the DAVE voice-encryption era: uses `discord.py` + `davey` + `PyNaCl` + `ffmpeg`.

## Before running — Discord Developer Portal (owner does this)

1. Open your application: https://discord.com/developers/applications
2. Go to **Bot** → **Privileged Gateway Intents** → turn **ON** "Message Content Intent" → Save.
   (Without this, the bot logs in but cannot read `!quran` commands.)

## Run locally (for testing)

```bash
pip install -r requirements.txt
# ffmpeg must be installed on the machine
# give the token via environment variable DISCORD_TOKEN, or a token.txt file next to bot.py
python bot.py
```

The bot logs in and waits. Join the voice channel yourself, then run `/start` (staff) — the bot joins and starts playing. In Discord, try `!play 18` or `/now` in any text channel.

## Deploy on Render (free Web Service)

The bot includes a tiny health server, so it can run as a free **Web Service** (same trick as the Madara bot):

1. New → **Web Service** → connect this repo (`Discord-Voice`).
2. Runtime: **Docker** (the Dockerfile installs ffmpeg). Region: Frankfurt. Instance type: **Free**.
3. Environment variable: `DISCORD_TOKEN` = the bot token (owner enters it in the dashboard — never in the repo).
4. Create the service. Logs should show `logged in as ...`.
5. Point an uptime pinger (e.g. UptimeRobot, 5-minute interval) at the service URL so it does not sleep.

Only secret needed anywhere: `DISCORD_TOKEN`. After each deploy/restart, join the voice channel and run `/start` once (staff) — the bot then keeps itself in the channel.

## Notes

- **Never** put the bot token in this repo. `token.txt` and `.env` are git-ignored.
- Change the reciter by editing `RECITER_BASE` at the top of `bot.py` (any mp3quran.net reciter mirror).
