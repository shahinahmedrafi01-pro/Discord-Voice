# Discord Voice — Quran Bot

A small Discord bot that plays Quran recitation in a voice channel, 24/7.
It streams **direct MP3 files from mp3quran.net** — no YouTube, no login, no verification blocks.

- There is exactly **one command**: `/playquran` (staff only — Administrator / Manage Server). It makes the bot join the ONE fixed voice channel and play the whole Quran from Surah 1 to Surah 114, then loop back to the start **without disconnecting** — forever, as long as the host runs.
- The bot never joins by itself after a restart: a staff member runs `/playquran` once; after that, a watchdog rejoins by itself whenever the bot is disconnected. Restarts wait for `/playquran` again and begin from Surah 1.
- There is **no stop command and no request/queue system** — by design, nobody can stop or interrupt the recitation.
- Reciter: Maher Al Muaiqly (mp3quran.net mirror, set in `bot.py`).
- The fixed channel is set in `bot.py` (`FIXED_VOICE_CHANNEL_ID`, or the `VOICE_CHANNEL_ID` env var).
- Built for the DAVE voice-encryption era: uses `discord.py` + `davey` + `PyNaCl` + `ffmpeg`.

## Before running — Discord Developer Portal (owner does this)

No privileged gateway intents are needed: the bot works entirely through the
single slash command `/playquran`, which registers itself from the code.

## Run locally (for testing)

```bash
pip install -r requirements.txt
# ffmpeg must be installed on the machine
# give the token via environment variable DISCORD_TOKEN, or a token.txt file next to bot.py
python bot.py
```

The bot logs in and waits. Run `/playquran` (staff) — the bot joins the fixed channel and starts playing the full Quran from the beginning.

## Deploy on Render (free Web Service)

The bot includes a tiny health server, so it can run as a free **Web Service** (same trick as the Madara bot):

1. New → **Web Service** → connect this repo (`Discord-Voice`).
2. Runtime: **Docker** (the Dockerfile installs ffmpeg). Region: Frankfurt. Instance type: **Free**.
3. Environment variable: `DISCORD_TOKEN` = the bot token (owner enters it in the dashboard — never in the repo).
4. Create the service. Logs should show `logged in as ...`.
5. Point an uptime pinger (e.g. UptimeRobot, 5-minute interval) at the service URL so it does not sleep.

Only secret needed anywhere: `DISCORD_TOKEN`. After each deploy/restart, run `/playquran` once (staff) — the bot then keeps itself in the channel.

## Notes

- **Never** put the bot token in this repo. `token.txt` and `.env` are git-ignored.
- Change the reciter by editing `RECITER_BASE` at the top of `bot.py` (any mp3quran.net reciter mirror).
