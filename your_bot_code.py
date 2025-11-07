import time, json, re, threading
from pathlib import Path
from datetime import datetime
import telebot
from telebot.types import Message
import os

# -------------------------
# CONFIG
# -------------------------
BOT_TOKEN = os.getenv("BOT_TOKEN")
OWNER_ID = int(os.getenv("OWNER_ID"))
DATA_FILE = Path("data.json")
LOG_FILE = Path("moderation.log")

bot = telebot.TeleBot(BOT_TOKEN, parse_mode=None)

# -------------------------
# Persistent data
# -------------------------
DEFAULT_DATA = {
    "banned": [],
    "mutes": {}
}

def load_data():
    if not DATA_FILE.exists():
        save_data(DEFAULT_DATA)
        return DEFAULT_DATA.copy()
    try:
        with DATA_FILE.open("r", encoding="utf-8") as f:
            return json.load(f)
    except:
        save_data(DEFAULT_DATA)
        return DEFAULT_DATA.copy()

def save_data(data):
    with DATA_FILE.open("w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

def log_action(text):
    ts = datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S UTC")
    line = f"[{ts}] {text}\n"
    with LOG_FILE.open("a", encoding="utf-8") as f:
        f.write(line)
    print(line.strip())

data = load_data()

URL_PATTERN = re.compile(r"(https?://[^\s]+)|([^\s]+\.(com|net|org|io|me|gg|xyz)(/[^\s]*)?)", re.IGNORECASE)

# -------------------------
# Helpers
# -------------------------
def is_owner(user_id):
    return user_id == OWNER_ID

def has_permission(user_id, chat_id, command_name=None):
    """Return True if user is bot owner or chat admin/creator"""
    if is_owner(user_id):
        return True
    try:
        member = bot.get_chat_member(chat_id, user_id)
        if member.status in ["creator", "administrator"]:
            return True
    except:
        pass
    return False

def parse_target_from_message(msg_text, reply_msg):
    parts = msg_text.split()
    if reply_msg and reply_msg.from_user:
        return reply_msg.from_user.id, parts[1:]
    if len(parts) >= 2:
        target = parts[1]
        if target.isdigit():
            return int(target), parts[2:]
        if target.startswith("@"):
            try:
                chat = bot.get_chat(target)
                return chat.id, parts[2:]
            except:
                return None, parts[2:]
    return None, parts[1:]

def parse_duration_to_seconds(s):
    if not s:
        return None
    s = s.lower().strip()
    try:
        if s.endswith("s"): return int(s[:-1])
        if s.endswith("m"): return int(s[:-1])*60
        if s.endswith("h"): return int(s[:-1])*3600
        if s.endswith("d"): return int(s[:-1])*86400
        return int(s)
    except:
        return None

def mod_command_wrapper(command_name):
    def decorator(cmd_func):
        def wrapper(msg: Message):
            if not has_permission(msg.from_user.id, msg.chat.id, command_name):
                bot.reply_to(msg, "You don't have permission to use this command")
                return
            cmd_func(msg)
        return wrapper
    return decorator

# -------------------------
# Commands
# -------------------------
@bot.message_handler(commands=["start"])
def cmd_start(msg: Message):
    bot.reply_to(msg, "Welcome! Moderation bot. /help")

@bot.message_handler(commands=["help"])
def cmd_help(msg: Message):
    help_text = (
        "/help - this message\n"
        "/mute <id/@username or reply> [duration]\n"
        "/unmute <id/@username or reply>\n"
        "/ban <id/@username or reply>\n"
        "/unban <id/@username or reply>\n"
        "/kick <id/@username or reply>\n"
    )
    bot.reply_to(msg, help_text)

# -------------------------
# Moderation functions
# -------------------------
def do_restrict(chat_id, user_id, mute=False, duration=None):
    until_ts = int(time.time()) + duration if duration else 0
    if mute:
        bot.restrict_chat_member(chat_id, user_id, until_date=until_ts or None,
                                 can_send_messages=False,
                                 can_send_media_messages=False,
                                 can_send_other_messages=False,
                                 can_add_web_page_previews=False)
        data["mutes"][str(user_id)] = {"chat_id": chat_id, "until": until_ts}
        save_data(data)
    else:
        bot.restrict_chat_member(chat_id, user_id, can_send_messages=True,
                                 can_send_media_messages=True,
                                 can_send_other_messages=True,
                                 can_add_web_page_previews=True)
        if str(user_id) in data.get("mutes", {}):
            del data["mutes"][str(user_id)]
            save_data(data)

def do_kick(chat_id, user_id):
    bot.kick_chat_member(chat_id, user_id)
    try: bot.unban_chat_member(chat_id, user_id)
    except: pass

def do_ban(chat_id, user_id):
    bot.kick_chat_member(chat_id, user_id)
    if user_id not in data["banned"]:
        data["banned"].append(user_id)
        save_data(data)

def do_unban(chat_id, user_id):
    bot.unban_chat_member(chat_id, user_id)
    if user_id in data.get("banned", []):
        data["banned"].remove(user_id)
        save_data(data)

# -------------------------
# Moderation commands
# -------------------------
@bot.message_handler(commands=["mute"])
@mod_command_wrapper("mute")
def cmd_mute(msg: Message):
    target_id, extra = parse_target_from_message(msg.text, msg.reply_to_message)
    if not target_id: return bot.reply_to(msg, "Cannot find target user")
    duration = parse_duration_to_seconds(extra[0]) if extra else None
    try:
        do_restrict(msg.chat.id, target_id, mute=True, duration=duration)
        bot.reply_to(msg, f"User {target_id} muted{' for '+str(duration)+'s' if duration else ' indefinitely'}.")
        log_action(f"MUTE {target_id} by {msg.from_user.id} duration={duration} in chat {msg.chat.id}")
    except Exception as e:
        bot.reply_to(msg, f"Failed: {e}")

@bot.message_handler(commands=["unmute"])
@mod_command_wrapper("unmute")
def cmd_unmute(msg: Message):
    target_id, _ = parse_target_from_message(msg.text, msg.reply_to_message)
    if not target_id: return bot.reply_to(msg, "Cannot find target user")
    try:
        do_restrict(msg.chat.id, target_id, mute=False)
        bot.reply_to(msg, f"User {target_id} unmuted.")
        log_action(f"UNMUTE {target_id} by {msg.from_user.id} in chat {msg.chat.id}")
    except Exception as e:
        bot.reply_to(msg, f"Failed: {e}")

@bot.message_handler(commands=["kick"])
@mod_command_wrapper("kick")
def cmd_kick(msg: Message):
    target_id, _ = parse_target_from_message(msg.text, msg.reply_to_message)
    if not target_id: return bot.reply_to(msg, "Cannot find target user")
    try:
        do_kick(msg.chat.id, target_id)
        bot.reply_to(msg, f"User {target_id} kicked.")
        log_action(f"KICK {target_id} by {msg.from_user.id} in chat {msg.chat.id}")
    except Exception as e:
        bot.reply_to(msg, f"Failed: {e}")

@bot.message_handler(commands=["ban"])
@mod_command_wrapper("ban")
def cmd_ban(msg: Message):
    target_id, _ = parse_target_from_message(msg.text, msg.reply_to_message)
    if not target_id: return bot.reply_to(msg, "Cannot find target user")
    try:
        do_ban(msg.chat.id, target_id)
        bot.reply_to(msg, f"User {target_id} banned.")
        log_action(f"BAN {target_id} by {msg.from_user.id} in chat {msg.chat.id}")
    except Exception as e:
        bot.reply_to(msg, f"Failed: {e}")

@bot.message_handler(commands=["unban"])
@mod_command_wrapper("unban")
def cmd_unban(msg: Message):
    target_id, _ = parse_target_from_message(msg.text, msg.reply_to_message)
    if not target_id: return bot.reply_to(msg, "Cannot find target user")
    try:
        do_unban(msg.chat.id, target_id)
        bot.reply_to(msg, f"User {target_id} unbanned.")
        log_action(f"UNBAN {target_id} by {msg.from_user.id} in chat {msg.chat.id}")
    except Exception as e:
        bot.reply_to(msg, f"Failed: {e}")

# -------------------------
# Forward & link filter
# -------------------------
@bot.message_handler(func=lambda m: True, content_types=['text','photo','video','document','sticker','video_note'])
def filter_and_monitor(msg: Message):
    if getattr(msg, "forward_from", None) or getattr(msg, "forward_from_chat", None):
        try: bot.delete_message(msg.chat.id, msg.message_id)
        except: pass
        bot.reply_to(msg, "Forwarded messages are not allowed.")
        log_action(f"DELETED forwarded message from {msg.from_user.id} in chat {msg.chat.id}")
        return
    text = (msg.text or "")
    if text and URL_PATTERN.search(text):
        try: bot.delete_message(msg.chat.id, msg.message_id)
        except: pass
        bot.reply_to(msg, "Links are not allowed.")
        log_action(f"DELETED link from {msg.from_user.id} in chat {msg.chat.id} -> {text[:200]}")

# -------------------------
# Auto-unmute thread
# -------------------------
def mute_watcher():
    while True:
        try:
            now = int(time.time())
            changed = False
            to_remove = []
            for uid_str, info in list(data.get("mutes", {}).items()):
                uid = int(uid_str)
                until = int(info.get("until",0) or 0)
                chat_id = int(info.get("chat_id",0))
                if until != 0 and now >= until:
                    try: do_restrict(chat_id, uid, mute=False)
                    except: pass
                    log_action(f"AUTO-UNMUTE {uid} in chat {chat_id}")
                    to_remove.append(uid_str)
                    changed = True
            for r in to_remove:
                if r in data.get("mutes", {}):
                    del data["mutes"][r]
            if changed: save_data(data)
        except Exception as e: print("mute_watcher error:", e)
        time.sleep(10)

threading.Thread(target=mute_watcher, daemon=True).start()

# -------------------------
# START BOT
# -------------------------
print("Bot is running...")
bot.infinity_polling(timeout=60, long_polling_timeout=30)
