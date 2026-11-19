# Quran Voice Bot — plays Quran recitation 24/7 in ONE fixed Discord voice channel.
# METHOD 1 included (pause-when-empty + 32 kbps), pushed 2026-11-20 on Rafi's word.
# Source: direct MP3 streams from mp3quran.net (NO YouTube, NO login, NO verification).
#
# Behaviour:
#   * There are exactly TWO commands, both staff only:
#       /playquran — join the fixed channel and play the whole Quran from
#         Surah 1 to Surah 114, then loop back to the start WITHOUT
#         disconnecting — forever, as long as the host runs.
#       /stopplay — disconnect from the voice channel and STAY out: the
#         watchdog will not rejoin until a staff member runs /playquran again.
#   * The bot never joins by itself after a restart: a staff member runs
#     /playquran once, and from then on a watchdog rejoins by itself whenever
#     the bot is disconnected — unless /stopplay was used. The bot NEVER
#     disconnects itself over encryption state: an earlier version did, every
#     few minutes, and kicked itself out of the channel while people were
#     listening (removed 2026-11-15).
#
# Setup: see README.md. Token via DISCORD_TOKEN env var or token.txt next to this file.
# NEVER share the token with anyone, never paste it in a chat, never commit it.

import os
import asyncio
import threading
import time
from http.server import BaseHTTPRequestHandler, HTTPServer

import discord
from discord import app_commands
from discord.ext import commands, tasks

# --- startup diagnostics + explicit libopus load ---
# discord.py's opus auto-detection can fail inside slim Docker images, which
# silently kills PCM playback; load libopus explicitly and log the versions in
# use so any future voice failure can be proven from the logs, not guessed.
try:
    if not discord.opus.is_loaded():
        discord.opus.load_opus("libopus.so.0")
except Exception as _e:
    print(f"[quran-bot] opus load failed: {_e}")
try:
    import importlib.metadata as _md

    print(
        f"[quran-bot] discord.py {_md.version('discord.py')}, "
        f"davey {_md.version('davey')}, opus loaded: {discord.opus.is_loaded()}"
    )
except Exception:
    pass

# ---------- config you can change ----------
RECITER_BASE = "https://server12.mp3quran.net/maher/"  # mp3quran.net mirror: 001.mp3 ... 114.mp3 — reciter: Maher Al Muaiqly (chosen by Rafi 2026-11-15; the earlier Banna recitation felt too slow to him)
START_SURAH = 1  # 1-114
FIXED_VOICE_CHANNEL_ID = 1571574151796490312  # HavenCraft MAIN server Quran channel (moved from the test server 2026-11-16 at Rafi's order; the test channel was 1557702195263311971)
WATCHDOG_SECONDS = 30
# --- Method 1: free-bandwidth saver (added 2026-11-19, pushed 2026-11-20) ---
# Rafi's target: stay within Render's free 5 GB/month until ~10-12 Dec. Two levers:
#   (a) encode at 32 kbps instead of 96 — Quran is voice-only, 32 stays clear;
#   (b) pause when nobody is listening, resume when someone joins.
# Render free 5 GB resets 1 Dec, so Dec gets a fresh 5 GB on top of this.
BITRATE_KBPS = 32
EMPTY_PAUSE_AFTER_SECONDS = 300  # 5 min grace: brief disconnects don't flap pause
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
intents.voice_states = True  # Method 1: see who is in the voice channel
bot = commands.Bot(command_prefix="!", intents=intents, help_command=None)

FFMPEG_OPTIONS = {
    "before_options": "-reconnect 1 -reconnect_streamed 1 -reconnect_delay_max 5",
    "options": "-vn",
}

state = {
    "playing": False,
    "current": None,        # surah number playing right now
    "resume": START_SURAH,  # next surah of the main 1->114 sequence
    "task": None,
    "synced": False,
    "started": False,  # True while playback is wanted: set by /playquran, cleared by /stopplay
    "paused": False,   # Method 1: True while paused because the channel is empty
    "empty_since": None,  # Method 1: monotonic time the channel first went empty
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
    if vc is not None and not vc.is_connected():
        # A voice client that silently lost its connection stays registered,
        # and every play() on it fails with "Not connected to voice". The old
        # code returned that dead client forever, so playback stalled for
        # good until a human restarted it (this is what stopped the bot
        # after its first full ~22h cycle, reported 2026-11-19). Drop the
        # dead client and connect fresh instead.
        try:
            await vc.disconnect(force=True)
        except Exception:
            pass
        vc = None
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
            # Give the voice encryption (DAVE) session a short chance to become
            # ready before playing, then play either way. Encryption is applied
            # per packet, so if the session becomes ready mid-surah, the rest of
            # the surah is audible. Never disconnect over this state: an earlier
            # version disconnected and reconnected in a loop (2026-11-15).
            for _ in range(15):
                if not _dave_stuck(vc):
                    break
                await asyncio.sleep(1)
            if _dave_stuck(vc):
                print("[quran-bot] note: voice encryption not ready yet; playing anyway")
            n = state["resume"]
            state["resume"] = n % 114 + 1
            state["current"] = n
            if n == START_SURAH:
                print("[quran-bot] starting the Quran from Surah 1 (new cycle)")
            done = asyncio.Event()

            def _after(_err, ev=done, sn=n):
                if _err is not None:
                    print(f"[quran-bot] playback error on surah {sn}: {_err}")
                bot.loop.call_soon_threadsafe(ev.set)

            try:
                # FFmpegOpusAudio: ffmpeg itself encodes Opus. The PCM path relies on
                # discord.py's internal encoder, which can send silent frames
                # (bot shows the green speaking ring but nobody hears anything).
                vc.play(discord.FFmpegOpusAudio(surah_url(n), bitrate=BITRATE_KBPS, **FFMPEG_OPTIONS), after=_after)
            except Exception as e:
                print(f"[quran-bot] play failed for surah {n}: {e}")
                state["current"] = None
                if not vc.is_connected():
                    # Dead voice client: remove it so the next loop pass
                    # reconnects fresh instead of failing on it forever.
                    try:
                        await vc.disconnect(force=True)
                    except Exception:
                        pass
                await asyncio.sleep(5)
                continue
            print(f"[quran-bot] now playing {surah_label(n)}")
            # While the surah plays, log any change in the voice encryption
            # state (diagnostics only — no action is taken on it).
            last_stuck = None
            stalled_since = None
            while not done.is_set():
                try:
                    await asyncio.wait_for(done.wait(), timeout=10)
                except asyncio.TimeoutError:
                    pass
                if done.is_set():
                    break
                # Stall guard: a dropped stream can swallow the after
                # callback, leaving the bot connected but silent forever.
                # If the player reports "not playing" for over a minute,
                # advance to the next surah instead of sitting silent.
                if state["paused"] or vc.is_playing():
                    stalled_since = None
                elif stalled_since is None:
                    stalled_since = time.monotonic()
                elif time.monotonic() - stalled_since > 60:
                    print(f"[quran-bot] playback stalled on {surah_label(n)}; moving to the next surah")
                    try:
                        vc.stop()
                    except Exception:
                        pass
                    break
                stuck = _dave_stuck(vc)
                if stuck != last_stuck:
                    print(f"[quran-bot] voice encryption ready: {not stuck}")
                    last_stuck = stuck
            state["current"] = None
    finally:
        state["playing"] = False
        state["current"] = None


def _ensure_task():
    t = state["task"]
    if t is None or t.done():
        state["task"] = asyncio.create_task(_play_loop())
    return state["task"]


def _human_listeners(ch) -> int:
    """Non-bot members currently in the voice channel."""
    if ch is None:
        return 0
    return sum(1 for m in ch.members if not getattr(m, "bot", False))


@tasks.loop(seconds=30)
async def _empty_watch():
    """Method 1: pause when nobody is listening, resume when someone joins.
    Runs every 30 s; the 5-min grace avoids flapping on brief disconnects.
    Pausing stops Opus packets (the bandwidth), while the bot stays in the
    channel and the surah position is kept (ffmpeg back-pressures)."""
    if not state["started"]:
        return
    ch = await _fixed_channel()
    if ch is None:
        return
    vc = discord.utils.get(bot.voice_clients, guild=ch.guild)
    if vc is None or not vc.is_connected():
        return
    now = time.monotonic()
    if _human_listeners(ch) == 0:
        if state["empty_since"] is None:
            state["empty_since"] = now
        elif now - state["empty_since"] >= EMPTY_PAUSE_AFTER_SECONDS and not state["paused"]:
            if vc.is_playing():
                vc.pause()
                state["paused"] = True
                print("[quran-bot] channel empty 5 min — paused to save bandwidth")
    else:
        state["empty_since"] = None
        if state["paused"]:
            try:
                vc.resume()
            except Exception as e:
                print(f"[quran-bot] resume failed: {e}")
            else:
                state["paused"] = False
                print("[quran-bot] listener joined — resumed playback")


@tasks.loop(seconds=WATCHDOG_SECONDS)
async def _watchdog():
    """If the bot is ever disconnected from the fixed channel, rejoin by itself.
    Does nothing until a staff member has started the bot with /playquran, and
    stays off after /stopplay until /playquran is used again."""
    if not state["started"]:
        return
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
    if not _empty_watch.is_running():
        _empty_watch.start()
    # No auto-join and no play loop here: the bot waits for a staff /playquran.


# ---------------- the two commands ----------------

def _is_staff(member) -> bool:
    perms = getattr(member, "guild_permissions", None)
    return bool(perms and (perms.administrator or perms.manage_guild))


async def _play_quran(user) -> str:
    if not _is_staff(user):
        return "This command is for server staff only (Admin / Moderator)."
    ch = await _fixed_channel()
    if ch is None:
        return "Bot is under maintenance."
    state["started"] = True  # from now on the watchdog keeps the bot in the channel
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
    return "Bot started. The full Quran is now playing from the beginning."


@bot.tree.command(name="playquran", description="Play the full Quran in the voice channel, start to finish, on loop (staff only)")
async def slash_play_quran(interaction: discord.Interaction):
    await interaction.response.send_message(await _play_quran(interaction.user))


async def _stop_quran(user) -> str:
    if not _is_staff(user):
        return "This command is for server staff only (Admin / Moderator)."
    ch = await _fixed_channel()
    if ch is None:
        return "Bot is under maintenance."
    vc = discord.utils.get(bot.voice_clients, guild=ch.guild)
    if not state["started"] and vc is None:
        return "Bot is already stopped."
    # Clear "started" FIRST so the watchdog cannot rejoin during teardown,
    # then stop the play loop so it cannot reconnect on its own either.
    state["started"] = False
    t = state["task"]
    state["task"] = None
    if t is not None and not t.done():
        t.cancel()
    state["playing"] = False
    state["paused"] = False
    state["empty_since"] = None
    state["current"] = None
    state["resume"] = START_SURAH  # the next /playquran starts from Surah 1 again
    if vc is not None:
        try:
            if vc.is_playing():
                vc.stop()
        except Exception:
            pass
        try:
            await vc.disconnect(force=True)
        except Exception as e:
            print(f"[quran-bot] stopplay disconnect failed: {e}")
    print("[quran-bot] stopped by staff (/stopplay); staying out until /playquran")
    return "Bot stopped. It will stay out of the voice channel until /playquran is used again."


@bot.tree.command(name="stopplay", description="Stop the Quran and leave the voice channel until /playquran is used again (staff only)")
async def slash_stop_quran(interaction: discord.Interaction):
    await interaction.response.send_message(await _stop_quran(interaction.user))


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
