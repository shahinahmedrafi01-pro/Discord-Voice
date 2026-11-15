# Quran Voice Bot — plays Quran recitation 24/7 in ONE fixed Discord voice channel.
# Source: direct MP3 streams from mp3quran.net (NO YouTube, NO login, NO verification).
#
# Behaviour:
#   * Auto-joins the fixed voice channel on startup and plays Surah 1 -> 114 in order, looping.
#     A restart simply starts again from Surah 1.
#   * Anyone can request a surah: /play <number> or !play <number>. The request is QUEUED and
#     plays right after the current surah ends. Requests line up in order. When the request
#     line is empty, the main sequence resumes where it left off
#     (example: 25 playing -> 50 requested -> 50 plays -> back to 26).
#   * /start (also !start) is staff-only: already in the channel -> says it is already online;
#     disconnected -> rejoins and plays; cannot join -> reports maintenance.
#   * /now (also !now) shows the surah playing now + the request line.
#   * There is deliberately NO stop command — nobody can stop the recitation.
#   * A watchdog rejoins the channel by itself if the bot is ever disconnected.
#
# Setup: see README.md. Token via DISCORD_TOKEN env var or token.txt next to this file.
# NEVER share the token with anyone, never paste it in a chat, never commit it.

import os
import asyncio
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

import discord
from discord import app_commands
from discord.ext import commands, tasks

# ---------- config you can change ----------
RECITER_BASE = "https://server8.mp3quran.net/bna/"  # mp3quran.net mirror: 001.mp3 ... 114.mp3
START_SURAH = 1  # 1-114
FIXED_VOICE_CHANNEL_ID = 1557702195263311971  # Rafi's chosen Quran voice channel (set 2026-11-14)
MAX_QUEUE_PER_USER = 3  # one person can line up at most this many requested surahs
WATCHDOG_SECONDS = 30
# -------------------------------------------

FIXED_VOICE_CHANNEL_ID = int(os.environ.get("VOICE_CHANNEL_ID", "") or FIXED_VOICE_CHANNEL_ID)
TOKEN_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "token.txt")

SURAHS = [
    "Al-Fatihah", "Al-Baqarah", "Aal-e-Imran", "An-Nisa", "Al-Maidah", "Al-An'am",
    "Al-A'raf", "Al-Anfal", "At-Tawbah", "Yunus", "Hud", "Yusuf", "Ar-Ra'd",
    "Ibrahim", "Al-Hijr", "An-Nahl", "Al-Isra", "Al-Kahf", "Maryam", "Ta-Ha",
    "Al-Anbiya", "Al-Hajj", "Al-Mu'minun", "An-Nur", "Al-Furqan", "Ash-Shu'ara",
    "An-Naml", "Al-Qasas", "Al-Ankabut", "Ar-Rum", "Luqman", "As-Sajdah",
    "Al-Ahzab", "Saba", "Fatir", "Ya-Sin", "As-Saffat", "Sad", "Az-Zumar",
    "Ghafir", "Fussilat", "Ash-Shura", "Az-Zukhruf", "Ad-Dukhan", "Al-Jathiyah",
    "Al-Ahqaf", "Muhammad", "Al-Fath", "Al-Hujurat", "Qaf", "Adh-Dhariyat",
    "At-Tur", "An-Najm", "Al-Qamar", "Ar-Rahman", "Al-Waqi'ah", "Al-Hadid",
    "Al-Mujadila", "Al-Hashr", "Al-Mumtahanah", "As-Saff", "Al-Jumu'ah",
    "Al-Munafiqun", "At-Taghabun", "At-Talaq", "At-Tahrim", "Al-Mulk",
    "Al-Qalam", "Al-Haqqah", "Al-Ma'arij", "Nuh", "Al-Jinn", "Al-Muzzammil",
    "Al-Muddaththir", "Al-Qiyamah", "Al-Insan", "Al-Mursalat", "An-Naba",
    "An-Nazi'at", "Abasa", "At-Takwir", "Al-Infitar", "Al-Mutaffifin",
    "Al-Inshiqaq", "Al-Buruj", "At-Tariq", "Al-A'la", "Al-Ghashiyah", "Al-Fajr",
    "Al-Balad", "Ash-Shams", "Al-Layl", "Ad-Duha", "Ash-Sharh", "At-Tin",
    "Al-Alaq", "Al-Qadr", "Al-Bayyinah", "Az-Zalzalah", "Al-Adiyat",
    "Al-Qari'ah", "At-Takathur", "Al-Asr", "Al-Humazah", "Al-Fil", "Quraysh",
    "Al-Ma'un", "Al-Kawthar", "Al-Kafirun", "An-Nasr", "Al-Masad", "Al-Ikhlas",
    "Al-Falaq", "An-Nas",
]

intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix="!", intents=intents)

FFMPEG_OPTIONS = {
    "before_options": "-reconnect 1 -reconnect_streamed 1 -reconnect_delay_max 5",
    "options": "-vn",
}

state = {
    "playing": False,
    "current": None,        # surah number playing right now
    "resume": START_SURAH,  # next surah of the main 1->114 sequence
    "queue": [],            # requested surahs: list of (surah:int, user_id:int)
    "task": None,
    "synced": False,
}


def surah_url(n: int) -> str:
    return f"{RECITER_BASE}{n:03d}.mp3"


def surah_label(n: int) -> str:
    return f"Surah {n} — {SURAHS[n - 1]}"


async def _fixed_channel():
    """Return the configured fixed voice channel, or None if not set/found/not a voice channel."""
    if not FIXED_VOICE_CHANNEL_ID:
        return None
    ch = bot.get_channel(FIXED_VOICE_CHANNEL_ID)
    if ch is None:
        try:
            ch = await bot.fetch_channel(FIXED_VOICE_CHANNEL_ID)
        except Exception:
            return None
    return ch if isinstance(ch, discord.VoiceChannel) else None


async def _ensure_vc():
    """Connect to the fixed voice channel (moving if needed). Returns the VoiceClient or None."""
    ch = await _fixed_channel()
    if ch is None:
        return None
    vc = discord.utils.get(bot.voice_clients, guild=ch.guild)
    if vc is None:
        vc = await ch.connect()
    elif vc.channel != ch:
        await vc.move_to(ch)
    return vc


def _dave_stuck(vc) -> bool:
    """True when the voice channel uses DAVE encryption but the encryption session
    is not ready. Audio sent in that state is dropped by Discord: the bot shows
    the green speaking ring, but nobody hears anything. When the channel does not
    use DAVE at all (protocol version 0), audio is fine and this returns False."""
    conn = getattr(vc, "_connection", None)
    if conn is None:
        return False
    try:
        return conn.dave_protocol_version != 0 and not conn.can_encrypt
    except Exception:
        return False


async def _play_loop():
    state["playing"] = True
    try:
        while True:
            vc = await _ensure_vc()
            if vc is None:
                await asyncio.sleep(10)
                continue
            # Wait for the voice encryption session to become ready before
            # playing. If it never becomes ready, reconnect the voice so the
            # handshake runs again from scratch.
            for _ in range(20):
                if not _dave_stuck(vc):
                    break
                await asyncio.sleep(1)
            if _dave_stuck(vc):
                print("[quran-bot] voice encryption not ready; reconnecting voice")
                try:
                    await vc.disconnect(force=True)
                except Exception:
                    pass
                await asyncio.sleep(3)
                continue
            if state["queue"]:
                n, _uid = state["queue"].pop(0)
            else:
                n = state["resume"]
                state["resume"] = n % 114 + 1
            state["current"] = n
            done = asyncio.Event()

            def _after(_err, ev=done):
                bot.loop.call_soon_threadsafe(ev.set)

            try:
                # FFmpegOpusAudio: ffmpeg itself encodes Opus. The PCM path relies on
                # discord.py's internal encoder, which can send silent frames
                # (bot shows the green speaking ring but nobody hears anything).
                vc.play(discord.FFmpegOpusAudio(surah_url(n), bitrate=96, **FFMPEG_OPTIONS), after=_after)
            except Exception as e:
                print(f"[quran-bot] play failed for surah {n}: {e}")
                state["current"] = None
                await asyncio.sleep(5)
                continue
            print(f"[quran-bot] now playing {surah_label(n)}")
            # While the surah plays, watch the encryption session. If it gets
            # stuck (Discord would silently drop the audio), reconnect the
            # voice connection and restart this surah.
            stuck_checks = 0
            while not done.is_set():
                try:
                    await asyncio.wait_for(done.wait(), timeout=10)
                except asyncio.TimeoutError:
                    pass
                if done.is_set():
                    break
                if _dave_stuck(vc):
                    stuck_checks += 1
                    if stuck_checks >= 3:
                        print("[quran-bot] voice encryption stuck during playback; reconnecting voice")
                        try:
                            vc.stop()
                        except Exception:
                            pass
                        try:
                            await vc.disconnect(force=True)
                        except Exception:
                            pass
                        state["resume"] = n  # restart this surah after reconnect
                        break
                else:
                    stuck_checks = 0
            state["current"] = None
    finally:
        state["playing"] = False
        state["current"] = None


def _ensure_task():
    t = state["task"]
    if t is None or t.done():
        state["task"] = asyncio.create_task(_play_loop())
    return state["task"]


@tasks.loop(seconds=WATCHDOG_SECONDS)
async def _watchdog():
    """If the bot is ever disconnected from the fixed channel, rejoin by itself."""
    ch = await _fixed_channel()
    if ch is None:
        return
    vc = discord.utils.get(bot.voice_clients, guild=ch.guild)
    if vc is None or not vc.is_connected() or vc.channel != ch:
        print("[quran-bot] watchdog: reconnecting to the fixed channel")
        try:
            await _ensure_vc()
        except Exception as e:
            print(f"[quran-bot] watchdog reconnect failed: {e}")
            return
    _ensure_task()


@bot.event
async def on_ready():
    print(f"[quran-bot] logged in as {bot.user}")
    if not state["synced"]:
        state["synced"] = True
        try:
            synced = await bot.tree.sync()
            print(f"[quran-bot] synced {len(synced)} slash commands")
        except Exception as e:
            print(f"[quran-bot] slash sync failed: {e}")
    if not _watchdog.is_running():
        _watchdog.start()
    _ensure_task()


# ---------------- shared command logic ----------------

async def _request_surah(user, n: int) -> str:
    if not (1 <= n <= 114):
        return "Surah number must be between 1 and 114."
    mine = sum(1 for _s, uid in state["queue"] if uid == user.id)
    if mine >= MAX_QUEUE_PER_USER:
        return f"You already have {MAX_QUEUE_PER_USER} surahs in the request line. Please wait for those to finish first."
    state["queue"].append((n, user.id))
    _ensure_task()
    pos = len(state["queue"])
    cur = state["current"]
    if cur:
        return (f"**{surah_label(n)}** added to the request line (position {pos}). "
                f"Now playing: **{surah_label(cur)}**. Your request will play in order.")
    return f"**{surah_label(n)}** added to the request line (position {pos})."


def _is_staff(member) -> bool:
    perms = getattr(member, "guild_permissions", None)
    return bool(perms and (perms.administrator or perms.manage_guild))


async def _start(user) -> str:
    if not _is_staff(user):
        return "This command is for server staff only (Admin / Moderator)."
    ch = await _fixed_channel()
    if ch is None:
        return "Bot is under maintenance."
    vc = discord.utils.get(bot.voice_clients, guild=ch.guild)
    if vc and vc.is_connected() and vc.channel == ch and state["playing"]:
        cur = state["current"]
        if cur:
            return f"Bot already online. Now playing: **{surah_label(cur)}**."
        return "Bot already online."
    try:
        await _ensure_vc()
    except Exception:
        return "Bot is under maintenance."
    _ensure_task()
    return "Bot started. Quran recitation is now playing."


def _now_text() -> str:
    cur = state["current"]
    if not state["playing"] or not cur:
        return "Nothing is playing right now."
    if state["queue"]:
        line = ", ".join(f"**{surah_label(s)}**" for s, _u in state["queue"])
    else:
        line = "empty"
    return f"Now playing: **{surah_label(cur)}**\nRequest line: {line}"


# ---------------- slash commands ----------------

@bot.tree.command(name="play", description="Request a surah by number — it plays after the current surah")
@app_commands.describe(surah="Surah number (1-114)")
async def slash_play(interaction: discord.Interaction, surah: app_commands.Range[int, 1, 114]):
    await interaction.response.send_message(await _request_surah(interaction.user, surah))


@bot.tree.command(name="start", description="Start the Quran bot (staff only)")
async def slash_start(interaction: discord.Interaction):
    await interaction.response.send_message(await _start(interaction.user))


@bot.tree.command(name="now", description="Show what is playing now and the request line")
async def slash_now(interaction: discord.Interaction):
    await interaction.response.send_message(_now_text())


# ---------------- prefix commands (same features, typed) ----------------

@bot.command(name="play")
async def prefix_play(ctx, surah: int = None):
    if surah is None:
        await ctx.send("Usage: `!play <surah number>` — example: `!play 50`")
        return
    await ctx.send(await _request_surah(ctx.author, surah))


@bot.command(name="start")
async def prefix_start(ctx):
    await ctx.send(await _start(ctx.author))


@bot.command(name="now")
async def prefix_now(ctx):
    await ctx.send(_now_text())


@bot.event
async def on_command_error(ctx, error):
    if isinstance(error, commands.BadArgument):
        await ctx.send("Please write the surah number correctly — example: `!play 50`")


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
        raise SystemExit("Token not found. Set the DISCORD_TOKEN environment variable, or put the bot token in a token.txt file next to bot.py.")
    bot.run(token)


if __name__ == "__main__":
    main()
