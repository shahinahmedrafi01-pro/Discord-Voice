# Quran Voice Bot — plays Quran recitation 24/7 in one Discord voice channel.
# Source: direct MP3 streams from mp3quran.net (NO YouTube, NO login, NO verification).
# Plays surah 001 -> 114 in order, then loops back to 001.
#
# Setup:
#   1. pip install -r requirements.txt   (also needs ffmpeg installed on the machine)
#   2. Give the bot token ONE of these two ways (never commit it, never share it, never paste it in a chat):
#        - environment variable:  DISCORD_TOKEN=<token>
#        - or a file named  token.txt  next to this file (one line, nothing else; already in .gitignore)
#   3. python bot.py
# Commands (in any text channel the bot can read):
#   !quran   -> bot joins YOUR voice channel and starts playing
#   !stop    -> bot stops and leaves the voice channel

import os
import asyncio
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
import discord
from discord.ext import commands

# ---------- config you can change ----------
# Reciter stream base (mp3quran.net mirror). Files are 001.mp3 ... 114.mp3 under this URL.
# Other reciters = different base URLs on mp3quran.net; change only this line to switch.
RECITER_BASE = "https://server8.mp3quran.net/bna/"
START_SURAH = 1  # 1-114
# Fixed voice channel: when set, the bot joins ONLY this voice channel (never any other)
# and starts playing automatically as soon as it comes online. Commands still work from
# any text channel. Can be overridden by the VOICE_CHANNEL_ID environment variable.
FIXED_VOICE_CHANNEL_ID = 0  # <-- the one voice channel's ID goes here
# -------------------------------------------

FIXED_VOICE_CHANNEL_ID = int(os.environ.get("VOICE_CHANNEL_ID", "") or FIXED_VOICE_CHANNEL_ID)

TOKEN_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "token.txt")

intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix="!", intents=intents)

FFMPEG_OPTIONS = {
    "before_options": "-reconnect 1 -reconnect_streamed 1 -reconnect_delay_max 5",
    "options": "-vn",
}

state = {"playing": False, "surah": START_SURAH, "task": None}


def surah_url(n: int) -> str:
    return f"{RECITER_BASE}{n:03d}.mp3"


async def play_loop(vc: discord.VoiceClient):
    """Play surahs in order, looping forever, until stopped."""
    while state["playing"]:
        n = state["surah"]
        source = discord.FFmpegPCMAudio(surah_url(n), **FFMPEG_OPTIONS)
        done = asyncio.Event()

        def after(_err, ev=done):
            bot.loop.call_soon_threadsafe(ev.set)

        vc.play(source, after=after)
        print(f"[quran-bot] now playing surah {n:03d} -> {surah_url(n)}")
        await done.wait()
        state["surah"] = n + 1 if n < 114 else 1


async def _fixed_channel():
    """Return the configured fixed voice channel, or None if not set/found."""
    if not FIXED_VOICE_CHANNEL_ID:
        return None
    ch = bot.get_channel(FIXED_VOICE_CHANNEL_ID)
    if ch is None:
        try:
            ch = await bot.fetch_channel(FIXED_VOICE_CHANNEL_ID)
        except Exception:
            return None
    return ch if isinstance(ch, discord.VoiceChannel) else None


async def _start_in(channel):
    """Connect to the given voice channel (if needed) and start the play loop."""
    vc = discord.utils.get(bot.voice_clients, guild=channel.guild)
    if vc is None:
        vc = await channel.connect()
    elif vc.channel != channel:
        await vc.move_to(channel)
    if state["playing"]:
        return vc
    state["playing"] = True
    state["surah"] = START_SURAH
    state["task"] = asyncio.create_task(play_loop(vc))
    return vc


@bot.event
async def on_ready():
    print(f"[quran-bot] logged in as {bot.user} — send !quran in the server to start.")
    ch = await _fixed_channel()
    if ch is not None and not state["playing"]:
        print(f"[quran-bot] fixed channel mode: auto-joining '{ch.name}' ({ch.id})")
        await _start_in(ch)


@bot.command(name="quran")
async def quran(ctx):
    """Start the Quran stream — in the fixed channel if one is set, else the caller's channel."""
    fixed = await _fixed_channel()
    if fixed is not None:
        await _start_in(fixed)
        await ctx.send(f"▶️ Quran play হচ্ছে এই channel-এ: **{fixed.name}** — থামাতে !stop")
        return
    if not ctx.author.voice or not ctx.author.voice.channel:
        await ctx.send("আগে তুমি নিজে একটা voice channel-এ join করো, তারপর !quran লেখো।")
        return
    await _start_in(ctx.author.voice.channel)
    await ctx.send(f"▶️ Quran play শুরু হলো — Surah {START_SURAH:03d} থেকে, একটানা চলবে। থামাতে !stop")


@bot.command(name="stop")
async def stop(ctx):
    state["playing"] = False
    if state["task"]:
        state["task"].cancel()
        state["task"] = None
    vc = ctx.voice_client
    if vc:
        if vc.is_playing():
            vc.stop()
        await vc.disconnect()
    await ctx.send("⏹️ Quran play বন্ধ করা হলো।")


# --- tiny health server: lets a free Web Service host (Render) run this bot ---
# Render free web services must open a port; this answers health checks on $PORT.
# An uptime pinger (e.g. UptimeRobot) hitting the service URL keeps it awake.
class _Health(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"Quran bot is running.")

    def log_message(self, *args):
        pass


def _serve_health():
    port = int(os.environ.get("PORT", "10000"))
    HTTPServer(("0.0.0.0", port), _Health).serve_forever()


def main():
    threading.Thread(target=_serve_health, daemon=True).start()
    token = os.environ.get("DISCORD_TOKEN", "").strip()
    if not token and os.path.exists(TOKEN_FILE):
        with open(TOKEN_FILE, "r", encoding="utf-8") as f:
            token = f.read().strip()
    if not token:
        raise SystemExit("Token পাওয়া যায়নি — DISCORD_TOKEN environment variable দাও, অথবা bot.py-এর পাশে token.txt ফাইলে bot token-টা বসাও।")
    bot.run(token)


if __name__ == "__main__":
    main()
