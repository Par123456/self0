# index.py

import os
import asyncio
import logging
import time
import math
import re
from datetime import datetime, timedelta
import random
import io # For in-memory file operations
from PIL import Image, ImageDraw, ImageFont # For image manipulations
import aiohttp # For asynchronous HTTP requests to external APIs
from googletrans import Translator, LANGUAGES # For translation
import wikipediaapi # For Wikipedia searches
import requests # For synchronous HTTP requests (if needed, but aiohttp is preferred)
from bs4 import BeautifulSoup # For web scraping (if needed)
from typing import Dict, Any, Optional, List, Union # For advanced Type Hinting
from functools import wraps # For decorators

# Database Integration (SQLModel/SQLite)
from sqlmodel import Field, Session, SQLModel, create_engine, select
from typing import Optional

# Additional libraries for new commands
import sys
import subprocess
import psutil # For system monitoring and uptime details
import qrcode # For QR code generation
import pyfiglet # For Figlet text
from spellchecker import SpellChecker # For spell correction (pip install pyspellchecker)
import base64 # For Base64 encoding/decoding

from pyrogram import Client, filters, idle
from pyrogram.types import (
    Message, InlineKeyboardMarkup, InlineKeyboardButton, CallbackQuery,
    ChatPermissions, ForceReply, InputMediaPhoto, InputMediaVideo
)
from pyrogram.enums import ChatAction, MessageEntityType
from pyrogram.errors import (
    FloodWait, RPCError, UserNotParticipant, PeerIdInvalid,
    UserAdminInvalid, ChatAdminRequired, BadRequest, MessageIdInvalid,
    Forbidden
)
from dotenv import load_dotenv

# =========================================================================
# SECTION 1: INITIAL SETUP AND ENVIRONMENT VARIABLES
# =========================================================================

# -------------------------------------------------------------------------
# Logging Configuration
# Sets up detailed logging to a file and console for debugging and monitoring.
# -------------------------------------------------------------------------
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[logging.FileHandler("userbot.log"), logging.StreamHandler()]
)
logger = logging.getLogger(__name__)

logger.info("Starting userbot initialization...")

# -------------------------------------------------------------------------
# Loading Environment Variables
# Fetches sensitive information and configuration from a .env file.
# -------------------------------------------------------------------------
logger.info("Loading environment variables from .env file...")
load_dotenv()

# Essential Telegram API credentials
API_ID: int = int(os.getenv("API_ID", "0"))
API_HASH: str = os.getenv("API_HASH", "")
if not API_ID or not API_HASH:
    logger.critical("API_ID or API_HASH is missing. Please set them in your .env file.")
    sys.exit(1)

# External API Keys (expanded for new features)
WEATHER_API_KEY: Optional[str] = os.getenv("WEATHER_API_KEY")
GOOGLE_SEARCH_API_KEY: Optional[str] = os.getenv("GOOGLE_SEARCH_API_KEY") # For Google Search
GOOGLE_CSE_ID: Optional[str] = os.getenv("GOOGLE_CSE_ID") # Custom Search Engine ID
URBAN_DICTIONARY_API_URL: str = "https://api.urbandictionary.com/v0/define?term="
MEME_API_URL: str = "https://meme-api.com/gimme" # Example meme API
GIF_API_KEY: Optional[str] = os.getenv("TENOR_API_KEY") # For Tenor/Giphy
TENOR_API_URL: str = "https://api.tenor.com/v1/search?q={query}&key={api_key}&limit={limit}"
# Add more API keys as functionalities are added

# Bot configuration
COMMAND_PREFIX: str = os.getenv("COMMAND_PREFIX", ".") # Prefix for bot commands
SESSION_NAME: str = os.getenv("SESSION_NAME", "my_userbot") # Session file name for Pyrogram

# Creating the Pyrogram client instance
# Plugins are handled manually in this single-file structure.
app = Client(
    SESSION_NAME,
    api_id=API_ID,
    api_hash=API_HASH,
    parse_mode="markdown" # Default to Markdown parsing for messages
)

logger.info(f"Pyrogram client created with SESSION_NAME: {SESSION_NAME}.")
logger.info(f"Command prefix: '{COMMAND_PREFIX}'")

# Global start time for uptime calculation
START_TIME: float = time.time()

# =========================================================================
# SECTION 2: GLOBAL VARIABLES AND DATABASE INTEGRATION
# This section defines global states and sets up SQLite database for persistence.
# =========================================================================

# -------------------------------------------------------------------------
# AFK Status Management
# Stores current AFK state and related information.
# -------------------------------------------------------------------------
AFK_STATUS: Dict[str, Any] = {
    "is_afk": False,
    "reason": None,
    "start_time": None,
    "last_afk_message_time": {} # {user_id: timestamp} to prevent AFK reply spam
}
AFK_MESSAGE_COOLDOWN: int = 60 # seconds, how often to reply to a user while AFK

# -------------------------------------------------------------------------
# Database Integration (SQLModel with SQLite)
# Defines database models and initializes the engine.
# -------------------------------------------------------------------------
DATABASE_URL: str = os.getenv("DATABASE_URL", "sqlite:///userbot.db")
engine = create_engine(DATABASE_URL)

# Ensure database tables are created on startup
def create_db_and_tables():
    SQLModel.metadata.create_all(engine)
    logger.info("Database and tables created/checked.")

# Database Models
class UserSetting(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    user_id: int = Field(index=True, unique=True)
    key: str
    value: str

class ChatSetting(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    chat_id: int = Field(index=True)
    key: str
    value: str

class AFKState(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    user_id: int = Field(index=True, unique=True)
    is_afk: bool = False
    reason: Optional[str] = None
    start_time: Optional[float] = None # Unix timestamp

class Reminder(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    user_id: int
    chat_id: int
    message_id: int # Original message ID to reply to or context
    remind_time: datetime
    text: str
    is_active: bool = True

class Note(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    user_id: int
    chat_id: int
    name: str = Field(index=True) # Name of the note
    content: str

class Warning(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    user_id: int
    chat_id: int
    admin_id: int
    reason: str
    timestamp: datetime = Field(default_factory=datetime.utcnow)

class ScheduledMessage(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    user_id: int # The user who scheduled it (the userbot's owner)
    chat_id: int # The chat where it should be sent
    send_time: datetime
    message_text: str
    is_sent: bool = False

# Initialize database tables
create_db_and_tables()

# Load AFK state from DB on startup
with Session(engine) as session:
    afk_db_state = session.exec(select(AFKState).where(AFKState.user_id == API_ID)).first() # Assuming userbot's own ID
    if afk_db_state:
        AFK_STATUS["is_afk"] = afk_db_state.is_afk
        AFK_STATUS["reason"] = afk_db_state.reason
        AFK_STATUS["start_time"] = afk_db_state.start_time
        logger.info(f"Loaded AFK state from DB: {AFK_STATUS['is_afk']}")

# -------------------------------------------------------------------------
# Global Caches and External API Clients
# Instances for frequently used services.
# -------------------------------------------------------------------------
translator = Translator() # Google Translate client
wiki_wiki_fa = wikipediaapi.Wikipedia('fa') # Wikipedia client for Farsi
wiki_wiki_en = wikipediaapi.Wikipedia('en') # Wikipedia client for English
spell = SpellChecker() # Spell checker instance

# =========================================================================
# SECTION 3: CENTRALIZED COMMAND DEFINITION (`COMMANDS` Dictionary)
# This dictionary is the core of your help panel and command recognition.
# It has been significantly expanded to reach 50+ commands.
# =========================================================================

COMMANDS: Dict[str, Dict[str, str]] = {
    "General": {
        "ping": "Checks the bot's response time.",
        "echo [text]": "Echoes back the provided text or replied message.",
        "type [text]": "Sends text with a typing animation.",
        "id": "Shows the current chat ID and sender's ID, or replied message's info.",
        "calc [expression]": "Evaluates a simple mathematical expression (e.g., `2+2*3`).",
        "purge [count]": "Deletes a specified number of recent messages. (Reply to a message)",
        "afk [reason]": "Toggles AFK (Away From Keyboard) mode with an optional reason.",
        "uptime": "Displays how long the bot has been running.",
        "eval [python code]": "Executes Python code. (Extremely dangerous, developer only)",
        "exec [shell command]": "Executes shell commands. (Extremely dangerous, developer only)",
        "logs": "Sends the bot's log file.",
        "restart": "Restarts the userbot (requires `systemd` or external script to manage)."
    },
    "Text Manipulation": {
        "tr [lang_code] [text/reply]": "Translates text to the specified language. Example: `.tr en Hello`",
        "ud [word]": "Gets the meaning of a word from Urban Dictionary (English only).",
        "reverse [text/reply]": "Reverses the input text.",
        "owo [text/reply]": "Converts text to 'OwO' language.",
        "mock [text/reply]": "Converts text to 'mOcKiNg SpOnGeBoB' style.",
        "ascii [text/reply]": "Converts text to ASCII Art (uses external API).",
        "figlet [text/reply]": "Converts text to Figlet style (large ASCII text).",
        "quote": "Displays a random quote.",
        "spell [word]": "Corrects the spelling of a word.",
        "base64e [text/reply]": "Encodes text into Base64.",
        "base64d [text/reply]": "Decodes Base64 text.",
        "bold [text/reply]": "Applies bold formatting to text.",
        "italic [text/reply]": "Applies italic formatting to text.",
        "code [text/reply]": "Applies code block formatting to text.",
        "strike [text/reply]": "Applies strikethrough formatting to text."
    },
    "Media & Fun": {
        "carbon [code/reply]": "Converts code to a Carbon.sh image (simulated).",
        "ss [url]": "Takes a screenshot of a website (simulated).",
        "qr [text]": "Generates a QR code for the given text.",
        "meme": "Sends a random meme.",
        "gif [query]": "Searches and sends a GIF.",
        "sticker [photo/reply]": "Converts a photo to a Telegram sticker.",
        "dice": "Rolls a dice and shows the result (1-6).",
        "coin": "Flips a coin (Heads/Tails).",
        "choose [opt1; opt2; ...]": "Randomly chooses from a list of options.",
        "shrug": "Sends the shrug emoticon. ¯\\_(ツ)_/¯",
        "table": "Sends a table flip emoticon. (╯°□°）╯︵ ┻━┻",
        "lovecalc [name1] [name2]": "Calculates compatibility between two names."
    },
    "Information & Search": {
        "wiki [query]": "Searches Wikipedia (Farsi/English preference).",
        "g [query]": "Searches Google for the given query (simulated).",
        "weather [city]": "Shows weather information for a specified city (OpenWeatherMap).",
        "whois [reply/user_id]": "Retrieves detailed information about a user.",
        "ginfo": "Retrieves comprehensive information about the current group/channel.",
        "covid [country]": "Displays COVID-19 statistics for a country (simulated API).",
        "time [city/timezone]": "Shows the current time in a specific city/timezone.",
        "shorten [url]": "Shortens a given URL using a public shortener API.",
        "hash [text]": "Generates a hash (MD5, SHA256) of the input text.",
        "remind [time] [message]": "Sets a reminder. Example: `.remind 1h take a break`",
        "note [name] [content]": "Saves a note with a given name.",
        "getnote [name]": "Retrieves a saved note.",
        "delnote [name]": "Deletes a saved note.",
        "allnotes": "Lists all saved notes."
    },
    "Admin Tools (requires bot admin rights)": {
        "ban [reply/user_id] [duration] [reason]": "Bans a user from the group (duration: 1m, 1h, 1d, permanent).",
        "unban [reply/user_id]": "Unbans a user from the group.",
        "kick [reply/user_id]": "Kicks a user from the group.",
        "mute [reply/user_id] [duration] [reason]": "Mutes a user in the group (duration: 1m, 1h, 1d, permanent).",
        "unmute [reply/user_id]": "Unmutes a user in the group.",
        "promote [reply/user_id] [rights]": "Promotes a user to admin with specified rights (e.g., `can_delete_messages`).",
        "demote [reply/user_id]": "Demotes an admin back to a regular user.",
        "pin [reply]": "Pins a replied message.",
        "unpin [reply/all]": "Unpins a replied message or all pinned messages.",
        "del [reply]": "Deletes a replied message.",
        "setgtitle [title]": "Changes the group's title.",
        "setgdesc [description]": "Changes the group's description.",
        "warn [reply/user_id] [reason]": "Warns a user.",
        "unwarn [reply/user_id]": "Removes one warning from a user.",
        "warnings [reply/user_id]": "Shows a user's warnings.",
        "setwelcome [text]": "Sets a custom welcome message for the group.",
        "delwelcome": "Deletes the custom welcome message.",
        "antilink [on/off]": "Toggles anti-link protection in the group.",
        "antiflood [on/off] [threshold]": "Toggles anti-flood protection in the group."
    },
    "Automation & Utils": {
        "dl [url]": "Downloads a file from a URL (e.g., photo/video).",
        "up [file_path]": "Uploads a local file to Telegram.",
        "autobio [text]": "Sets your account's automatic biography.",
        "autoname [first] [last]": "Sets your account's first and last name automatically.",
        "scheduled [time] [message]": "Schedules a message to be sent at a future time.",
        "count [text/reply]": "Counts words, characters, or lines in the text.",
        "telegraph [title] [author] [text/reply]": "Creates a Telegraph article.",
        "imgedit [rotate/resize] [value] [reply]": "Performs basic image edits (rotate, resize).",
        "tofile [reply]": "Converts a media message to a document file.",
        "tosticker [reply]": "Converts a photo to a static sticker.",
        "tovoice [reply]": "Converts a text message to a voice message (TTS - simulated)."
    },
    "Developer": {
        # eval/exec are in General for convenience, but truly developer-centric
        "debug": "Shows internal debug information about the bot."
    }
}

# =========================================================================
# SECTION 4: CORE HELPER FUNCTIONS
# These functions encapsulate common logic to avoid code repetition.
# -------------------------------------------------------------------------
# Admin Permissions Checker Decorator
# A decorator to check if the userbot has specific admin rights in a chat.
# -------------------------------------------------------------------------
def require_admin_rights(permissions: List[str]):
    def decorator(func):
        @wraps(func)
        async def wrapper(client: Client, message: Message, *args, **kwargs):
            if not message.chat.type in ["group", "supergroup"]:
                await message.edit("`This command only works in groups.`")
                return

            try:
                me_member = await client.get_chat_member(message.chat.id, client.me.id)
                
                missing_perms = []
                for perm in permissions:
                    # Special handling for 'admin' implies full rights
                    if perm == 'admin' and not me_member.status.ADMINISTRATOR:
                        missing_perms.append('Administrator')
                    elif not getattr(me_member, perm, False):
                        missing_perms.append(perm.replace("can_", "").replace("_", " ").title())
                
                if missing_perms:
                    await message.edit(
                        f"`I need the following admin rights to perform this action:`\n"
                        f"**`{', '.join(missing_perms)}`**"
                    )
                    logger.warning(
                        f"Bot lacks permissions in chat {message.chat.id} for command "
                        f"'{message.command[0]}'. Missing: {', '.join(missing_perms)}"
                    )
                    return
            except ChatAdminRequired:
                await message.edit("`I need to be an admin in this group to use this command.`")
                logger.warning(
                    f"Bot is not admin in chat {message.chat.id} for command '{message.command[0]}'."
                )
                return
            except Exception as e:
                logger.error(f"Error checking admin rights: {e}", exc_info=True)
                await message.edit(f"`Error checking admin rights: {e}`")
                return
            
            await func(client, message, *args, **kwargs)
        return wrapper
    return decorator


async def get_reply_text(message: Message) -> Optional[str]:
    """
    Returns the text of the input message or the replied message.
    """
    if message.reply_to_message and message.reply_to_message.text:
        return message.reply_to_message.text
    return None

async def extract_arg(message: Message) -> Optional[str]:
    """
    Extracts the argument string after the command.
    """
    if len(message.command) > 1:
        return " ".join(message.command[1:])
    return None

async def get_target_user_id(message: Message) -> Optional[int]:
    """
    Extracts the target user's ID from a replied message or as an argument.
    """
    if message.reply_to_message and message.reply_to_message.from_user:
        return message.reply_to_message.from_user.id
    if len(message.command) > 1:
        try:
            return int(message.command[1])
        except ValueError:
            # Try to resolve username to ID
            try:
                user = await app.get_users(message.command[1])
                return user.id
            except PeerIdInvalid:
                return None
    return None

async def get_target_chat_id(message: Message) -> int:
    """
    Returns the ID of the current chat.
    """
    return message.chat.id

def format_time_difference(seconds: float) -> str:
    """
    Formats a time difference in seconds into a human-readable string.
    """
    days, remainder = divmod(seconds, 86400)
    hours, remainder = divmod(remainder, 3600)
    minutes, secs = divmod(remainder, 60)
    
    parts = []
    if days > 0: parts.append(f"{int(days)} days")
    if hours > 0: parts.append(f"{int(hours)} hours")
    if minutes > 0: parts.append(f"{int(minutes)} minutes")
    if secs > 0 or not parts: parts.append(f"{int(secs)} seconds") # Ensure something is always shown

    return ", ".join(parts)

async def check_userbot_rights_in_chat(chat_id: int, permissions: List[str]) -> bool:
    """
    Checks if the userbot has the specified admin permissions in a given chat.
    """
    try:
        me_member = await app.get_chat_member(chat_id, app.me.id)
        for perm in permissions:
            if perm == 'admin' and not me_member.status.ADMINISTRATOR:
                return False
            elif not getattr(me_member, perm, False):
                return False
        return True
    except ChatAdminRequired:
        return False
    except Exception as e:
        logger.error(f"Error checking bot permissions in chat {chat_id}: {e}", exc_info=True)
        return False

async def http_get_json(url: str, session: aiohttp.ClientSession, params: Optional[Dict] = None) -> Optional[Dict]:
    """
    Performs an asynchronous HTTP GET request and returns JSON response.
    """
    try:
        async with session.get(url, params=params, timeout=10) as response:
            if response.status == 200:
                return await response.json()
            else:
                logger.warning(f"HTTP GET failed for {url} with status {response.status}")
                return None
    except aiohttp.ClientError as e:
        logger.error(f"AIOHTTP Client Error for {url}: {e}", exc_info=True)
        return None
    except asyncio.TimeoutError:
        logger.warning(f"HTTP GET timeout for {url}")
        return None
    except Exception as e:
        logger.error(f"Unexpected error during HTTP GET for {url}: {e}", exc_info=True)
        return None

# =========================================================================
# SECTION 5: IMPLEMENTATION OF GENERAL COMMANDS
# These are basic, fundamental commands for bot interaction and utility.
# =========================================================================

# -------------------------------------------------------------------------
# Command: .ping - Checks bot's response time.
# -------------------------------------------------------------------------
@app.on_message(filters.me & filters.command("ping", prefixes=COMMAND_PREFIX))
async def ping_command_handler(client: Client, message: Message):
    """
    Handles the .ping command to measure bot latency.
    """
    logger.info(f"Command {COMMAND_PREFIX}ping executed by user {message.from_user.id}.")
    start_time = asyncio.get_event_loop().time()
    try:
        sent_message = await message.edit("`Pinging... 🚀`")
        end_time = asyncio.get_event_loop().time()
        latency = round((end_time - start_time) * 1000)
        
        # Optionally, check Telegram API latency
        telegram_start = asyncio.get_event_loop().time()
        await app.send_chat_action(message.chat.id, ChatAction.TYPING)
        await asyncio.sleep(0.1) # Give some time for action to register
        await app.send_chat_action(message.chat.id, ChatAction.CANCEL)
        telegram_end = asyncio.get_event_loop().time()
        telegram_latency = round((telegram_end - telegram_start) * 1000)

        response_text = (
            f"**Pong!** 🏓\n"
            f"• `Message Edit Latency: {latency} ms`\n"
            f"• `Telegram API Latency: {telegram_latency} ms`"
        )
        await sent_message.edit(response_text)
        logger.info(f"Ping successful: {latency}ms (Edit), {telegram_latency}ms (API).")
    except FloodWait as e:
        logger.warning(f"FloodWait encountered during ping: {e.value} seconds.")
        await asyncio.sleep(e.value)
        await message.edit(f"**Pong!** 🏓\n`Time: (after delay) {e.value}s`")
    except Exception as e:
        logger.error(f"Error in ping command: {e}", exc_info=True)
        await message.edit(f"An error occurred: `{e}`")

# -------------------------------------------------------------------------
# Command: .echo - Reflects input text.
# -------------------------------------------------------------------------
@app.on_message(filters.me & filters.command("echo", prefixes=COMMAND_PREFIX))
async def echo_command_handler(client: Client, message: Message):
    """
    Handles the .echo command to reflect the provided text or replied message.
    Supports markdown parsing.
    """
    logger.info(f"Command {COMMAND_PREFIX}echo executed by user {message.from_user.id}.")
    text_to_echo = await extract_arg(message)
    if not text_to_echo and message.reply_to_message:
        text_to_echo = message.reply_to_message.text
    
    if text_to_echo:
        try:
            # Pyrogram client is configured with parse_mode="markdown"
            await message.edit(text_to_echo)
            logger.info(f"Echoed text: '{text_to_echo}'")
        except Exception as e:
            logger.error(f"Error in echo command: {e}", exc_info=True)
            await message.edit(f"An error occurred: `{e}`")
    else:
        await message.edit(f"`Please provide text to echo! (Example: {COMMAND_PREFIX}echo Hello World)`")

# -------------------------------------------------------------------------
# Command: .type - Simulates typing animation.
# -------------------------------------------------------------------------
@app.on_message(filters.me & filters.command("type", prefixes=COMMAND_PREFIX))
async def type_command_handler(client: Client, message: Message):
    """
    Handles the .type command to simulate typing out a message.
    """
    logger.info(f"Command {COMMAND_PREFIX}type executed by user {message.from_user.id}.")
    text_to_type = await extract_arg(message)
    if not text_to_type and message.reply_to_message:
        text_to_type = message.reply_to_message.text

    if text_to_type:
        typing_speed = 0.05  # seconds between each character
        full_text = ""
        try:
            await client.send_chat_action(message.chat.id, ChatAction.TYPING)
            for char in text_to_type:
                full_text += char
                await message.edit(full_text + "▌") # Appends a cursor character
                await asyncio.sleep(typing_speed)
            await message.edit(full_text) # Remove cursor at the end
            logger.info(f"Typed text: '{text_to_type}'")
        except Exception as e:
            logger.error(f"Error in type command: {e}", exc_info=True)
            await message.edit(f"Error executing type command: `{e}`")
    else:
        await message.edit(f"`Please provide text to type! (Example: {COMMAND_PREFIX}type My awesome bot)`")

# -------------------------------------------------------------------------
# Command: .id - Displays chat and user IDs.
# -------------------------------------------------------------------------
@app.on_message(filters.me & filters.command("id", prefixes=COMMAND_PREFIX))
async def id_command_handler(client: Client, message: Message):
    """
    Handles the .id command to display current chat ID, sender ID,
    and replied message/user IDs if applicable.
    """
    logger.info(f"Command {COMMAND_PREFIX}id executed by user {message.from_user.id}.")
    chat_id = message.chat.id
    user_id = message.from_user.id
    
    response_text = f"**👤 ID Information:**\n"
    response_text += f"▪️ **Chat ID:** `{chat_id}`\n"
    response_text += f"▪️ **Sender (You) ID:** `{user_id}`\n"

    if message.reply_to_message:
        reply_to_user_id = message.reply_to_message.from_user.id if message.reply_to_message.from_user else "N/A"
        reply_to_message_id = message.reply_to_message.id
        response_text += f"▪️ **Replied User ID:** `{reply_to_user_id}`\n"
        response_text += f"▪️ **Replied Message ID:** `{reply_to_message_id}`\n"
        if message.reply_to_message.sender_chat: # If replied to a channel post
            response_text += f"▪️ **Replied Channel ID:** `{message.reply_to_message.sender_chat.id}`\n"
            response_text += f"▪️ **Replied Channel Username:** `@{message.reply_to_message.sender_chat.username or 'N/A'}`\n"
        logger.info(f"ID: Chat={chat_id}, User={user_id}, Replied_User={reply_to_user_id}, Replied_Msg={reply_to_message_id}")
    else:
        logger.info(f"ID: Chat={chat_id}, User={user_id}")
    
    try:
        await message.edit(response_text)
    except Exception as e:
        logger.error(f"Error in ID command: {e}", exc_info=True)
        await message.edit(f"An error occurred: `{e}`")

# -------------------------------------------------------------------------
# Command: .calc - Simple calculator.
# -------------------------------------------------------------------------
@app.on_message(filters.me & filters.command("calc", prefixes=COMMAND_PREFIX))
async def calc_command_handler(client: Client, message: Message):
    """
    Handles the .calc command to evaluate simple mathematical expressions.
    Uses a safer approach than direct eval for basic operations.
    """
    logger.info(f"Command {COMMAND_PREFIX}calc executed by user {message.from_user.id}.")
    expression = await extract_arg(message)
    if not expression:
        await message.edit(f"`Please provide a mathematical expression! (Example: {COMMAND_PREFIX}calc 10 * 5 + 3)`")
        return

    # Advanced sanitization for safety: Only allow numbers, basic operators, and parentheses
    # This regex is strict and disallows function calls, variable names, etc.
    sanitized_expression = re.sub(r'[^0-9+\-*/().\s]', '', expression)

    if not sanitized_expression:
        await message.edit("`Invalid expression. Only numbers, +, -, *, /, (, ) are allowed.`")
        return

    try:
        # Use a safe evaluation context or a dedicated math parser if full security is needed.
        # For simplicity and common use, 'eval' with strong sanitization is often used in userbots.
        # For true enterprise-level security, consider libraries like 'numexpr' or 'asteval'.
        result = str(eval(sanitized_expression)) # eval is still potentially risky, but minimized by regex
        await message.edit(f"**Result:** `{expression} = {result}`")
        logger.info(f"Calculated '{expression}' to '{result}'.")
    except SyntaxError:
        await message.edit("`Syntax Error: Please check your mathematical expression.`")
        logger.warning(f"Syntax error in calc command for expression: '{expression}'")
    except ZeroDivisionError:
        await message.edit("`Error: Division by zero.`")
        logger.warning(f"ZeroDivisionError in calc command for expression: '{expression}'")
    except Exception as e:
        logger.error(f"Error in calc command: {e}", exc_info=True)
        await message.edit(f"Error in calculation: `{e}`\n`Ensure the expression is correct and simple.`")

# -------------------------------------------------------------------------
# Command: .purge - Deletes messages.
# -------------------------------------------------------------------------
@app.on_message(filters.me & filters.command("purge", prefixes=COMMAND_PREFIX))
@require_admin_rights(['can_delete_messages'])
async def purge_command_handler(client: Client, message: Message):
    """
    Handles the .purge command to delete a specified number of messages.
    Requires bot admin rights to delete messages.
    """
    logger.info(f"Command {COMMAND_PREFIX}purge executed by user {message.from_user.id}.")
    if not message.reply_to_message:
        await message.edit("`To purge messages, you must reply to a message.`")
        return

    try:
        count_str = await extract_arg(message)
        count = int(count_str) if count_str else 1
        if count <= 0:
            raise ValueError("Count must be positive.")
    except ValueError:
        await message.edit("`Please provide a positive integer for the number of messages to delete.`")
        return

    messages_to_delete: List[int] = []
    # Add the command message itself to the list for deletion
    messages_to_delete.append(message.id)

    # Start from the replied message (inclusive)
    target_msg_id = message.reply_to_message.id
    
    try:
        # Pyrogram's iter_messages works in descending order (newest to oldest)
        # We need messages from target_msg_id up to 'count' messages backwards.
        async for msg in client.iter_messages(message.chat.id, offset_id=target_msg_id, limit=count):
            messages_to_delete.append(msg.id)
            if len(messages_to_delete) > count: # +1 for the command message
                break
        
        # Ensure unique message IDs and sort them to delete efficiently (optional, Pyrogram handles lists)
        messages_to_delete = sorted(list(set(messages_to_delete)))

        await client.delete_messages(message.chat.id, messages_to_delete)
        
        # Optional: Send a temporary confirmation message and delete it
        # confirmation_msg = await client.send_message(message.chat.id, f"`{len(messages_to_delete) - 1} messages deleted.`")
        # await asyncio.sleep(2)
        # await client.delete_messages(message.chat.id, confirmation_msg.id)
        
        logger.info(f"Purge command executed. {len(messages_to_delete)} messages deleted in chat {message.chat.id}.")
    except ChatAdminRequired:
        # This should be caught by decorator, but as fallback
        await message.edit("`I need admin rights to delete these messages.`")
        logger.warning(f"Bot is not admin in {message.chat.id} (for purge).")
    except Exception as e:
        logger.error(f"Error deleting messages in purge command: {e}", exc_info=True)
        await client.send_message(message.chat.id, f"Error deleting messages: `{e}`")

# -------------------------------------------------------------------------
# Command: .afk - Toggles Away From Keyboard mode.
# -------------------------------------------------------------------------
@app.on_message(filters.me & filters.command("afk", prefixes=COMMAND_PREFIX))
async def afk_command_handler(client: Client, message: Message):
    """
    Handles the .afk command to toggle AFK status.
    Updates global AFK_STATUS and persists it to the database.
    """
    global AFK_STATUS
    logger.info(f"Command {COMMAND_PREFIX}afk executed by user {message.from_user.id}.")

    with Session(engine) as session:
        afk_db_state = session.exec(select(AFKState).where(AFKState.user_id == client.me.id)).first()

        if AFK_STATUS["is_afk"]:
            AFK_STATUS["is_afk"] = False
            AFK_STATUS["reason"] = None
            AFK_STATUS["start_time"] = None
            AFK_STATUS["last_afk_message_time"].clear() # Clear cooldowns

            if afk_db_state:
                afk_db_state.is_afk = False
                afk_db_state.reason = None
                afk_db_state.start_time = None
                session.add(afk_db_state)
            
            await message.edit("**`AFK mode disabled. I'm back! 🎉`**")
            logger.info("AFK mode deactivated.")
        else:
            reason = await extract_arg(message)
            if not reason:
                reason = "Not available at the moment."
            
            current_time = asyncio.get_event_loop().time()
            AFK_STATUS["is_afk"] = True
            AFK_STATUS["reason"] = reason
            AFK_STATUS["start_time"] = current_time
            AFK_STATUS["last_afk_message_time"].clear() # Clear cooldowns for new AFK state

            if not afk_db_state:
                afk_db_state = AFKState(user_id=client.me.id)
            afk_db_state.is_afk = True
            afk_db_state.reason = reason
            afk_db_state.start_time = current_time
            session.add(afk_db_state)
            
            await message.edit(f"**`I am now in AFK mode.`**\n**Reason:** `{reason}`")
            logger.info(f"AFK mode activated. Reason: {reason}")
        
        session.commit()

# Handler for replying to messages when AFK
@app.on_message(filters.private & ~filters.me | filters.group & ~filters.me & filters.mentioned)
async def afk_reply_handler(client: Client, message: Message):
    """
    Listens for private messages or mentions when the bot is AFK
    and sends an automated AFK reply.
    """
    global AFK_STATUS
    if AFK_STATUS["is_afk"] and message.from_user and not message.from_user.is_bot:
        # Ignore messages from self or forwarded from self (e.g. edited by self)
        if message.from_user.id == client.me.id:
            return
        # Ignore if the message is from an anonymous admin and not a direct reply/mention
        if message.sender_chat and message.sender_chat.id != message.chat.id and not message.mentioned:
            return

        user_id = message.from_user.id
        current_time = asyncio.get_event_loop().time()

        # Check cooldown to prevent spamming the same user
        if user_id in AFK_STATUS["last_afk_message_time"]:
            if (current_time - AFK_STATUS["last_afk_message_time"][user_id]) < AFK_MESSAGE_COOLDOWN:
                return # Still in cooldown, do not reply
        
        AFK_STATUS["last_afk_message_time"][user_id] = current_time

        elapsed_time_seconds = current_time - (AFK_STATUS["start_time"] or current_time) # Use current_time if start_time is None
        time_string = format_time_difference(elapsed_time_seconds)
        
        reason_text = f"**Reason:** `{AFK_STATUS['reason']}`\n" if AFK_STATUS["reason"] else ""
        
        response = (
            f"**`I am currently unavailable.`**\n"
            f"{reason_text}"
            f"**AFK Duration:** `{time_string}`"
        )
        
        try:
            await message.reply_text(response)
            logger.info(f"Sent AFK reply to {message.from_user.first_name} ({message.from_user.id}).")
        except Exception as e:
            logger.error(f"Error sending AFK reply to {message.from_user.id}: {e}", exc_info=True)

# -------------------------------------------------------------------------
# Command: .uptime - Displays bot uptime.
# -------------------------------------------------------------------------
@app.on_message(filters.me & filters.command("uptime", prefixes=COMMAND_PREFIX))
async def uptime_command_handler(client: Client, message: Message):
    """
    Handles the .uptime command to display the bot's running duration.
    """
    logger.info(f"Command {COMMAND_PREFIX}uptime executed by user {message.from_user.id}.")
    current_time = time.time()
    elapsed_time_seconds = current_time - START_TIME

    uptime_string = format_time_difference(elapsed_time_seconds)
    
    try:
        # Get system uptime as well for richer info
        system_uptime_seconds = time.time() - psutil.boot_time()
        system_uptime_string = format_time_difference(system_uptime_seconds)

        response_text = (
            f"**Bot has been running for:** `{uptime_string}`\n"
            f"**System Uptime:** `{system_uptime_string}`\n"
            f"**Started On:** `{datetime.fromtimestamp(START_TIME).strftime('%Y-%m-%d %H:%M:%S UTC')}`"
        )
        await message.edit(response_text)
        logger.info(f"Uptime displayed: Bot={uptime_string}, System={system_uptime_string}")
    except Exception as e:
        logger.error(f"Error in uptime command: {e}", exc_info=True)
        await message.edit(f"An error occurred: `{e}`")

# -------------------------------------------------------------------------
# Command: .eval - Executes Python code (Developer only - HIGH RISK!).
# -------------------------------------------------------------------------
@app.on_message(filters.me & filters.command("eval", prefixes=COMMAND_PREFIX))
async def eval_command_handler(client: Client, message: Message):
    """
    Handles the .eval command to execute arbitrary Python code.
    EXTREMELY DANGEROUS - ONLY FOR TRUSTED DEVELOPERS.
    """
    logger.warning(f"Command {COMMAND_PREFIX}eval executed by user {message.from_user.id}. (HIGH RISK!)")
    code = await extract_arg(message)
    if not code:
        await message.edit(f"`Please provide code to execute! (Example: {COMMAND_PREFIX}eval print('Hello'))`")
        return

    # Capture stdout
    old_stdout = sys.stdout
    redirected_output = io.StringIO()
    sys.stdout = redirected_output

    try:
        # Define a safe execution environment for eval/exec
        # Making app and message available in the context
        exec_globals = {
            'app': client,
            'client': client,
            'message': message,
            '__import__': __import__,
            'asyncio': asyncio,
            'pyrogram': pyrogram,
            'filters': filters,
            'datetime': datetime,
            'timedelta': timedelta,
            're': re,
            'os': os,
            'time': time,
            'math': math,
            'random': random,
            'io': io,
            'PIL': Image,
            'aiohttp': aiohttp,
            'googletrans': translator, # Expose translator instance
            'wikipediaapi': wiki_wiki_fa, # Expose wiki instance
            'requests': requests,
            'bs4': BeautifulSoup,
            'typing': typing,
            'Session': Session, 'engine': engine, 'select': select, # DB objects
            'UserSetting': UserSetting, 'ChatSetting': ChatSetting, 'AFKState': AFKState,
            'Reminder': Reminder, 'Note': Note, 'Warning': Warning, 'ScheduledMessage': ScheduledMessage
        }
        exec_locals = {}
        
        # Check if the code is asynchronous
        if code.startswith("await "):
            # Compile into an async function and await its execution
            # This allows direct 'await' calls within the eval
            compiled_code = compile(f"async def _eval_wrapper():\n{code}", "<string>", "exec")
            _eval_obj = {}
            exec(compiled_code, exec_globals, _eval_obj)
            result = await _eval_obj["_eval_wrapper"]()
        else:
            # For synchronous code, just eval it
            result = eval(code, exec_globals, exec_locals)

        output = redirected_output.getvalue()
        response = ""
        if output:
            response += f"**Output:**\n```\n{output}```\n"
        if result is not None:
            response += f"**Result:**\n`{result}`"
        
        if not response:
            response = "**Execution completed with no output or result.**"

        await message.edit(response)
        logger.info(f"Eval successful: {code}, result: {result}, output: {output}")

    except Exception as e:
        output = redirected_output.getvalue()
        response = f"**Error:**\n`{type(e).__name__}: {e}`"
        if output:
            response += f"\n**Error Output:**\n```\n{output}```"
        await message.edit(response)
        logger.error(f"Error in eval command for code: '{code}': {e}", exc_info=True)
    finally:
        sys.stdout = old_stdout # Restore stdout

# -------------------------------------------------------------------------
# Command: .exec - Executes shell commands (Developer only - HIGH RISK!).
# -------------------------------------------------------------------------
@app.on_message(filters.me & filters.command("exec", prefixes=COMMAND_PREFIX))
async def exec_command_handler(client: Client, message: Message):
    """
    Handles the .exec command to execute arbitrary shell commands.
    EXTREMELY DANGEROUS - ONLY FOR TRUSTED DEVELOPERS.
    """
    logger.warning(f"Command {COMMAND_PREFIX}exec executed by user {message.from_user.id}. (HIGH RISK!)")
    command = await extract_arg(message)
    if not command:
        await message.edit(f"`Please provide a command to execute! (Example: {COMMAND_PREFIX}exec ls -l)`")
        return

    await message.edit(f"`Executing: {command}`")
    try:
        # Execute shell command
        process = await asyncio.create_subprocess_shell(
            command,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE
        )
        stdout, stderr = await process.communicate()
        
        response_parts = []
        if stdout:
            response_parts.append(f"**Output:**\n```\n{stdout.decode('utf-8', errors='ignore').strip()}```")
        if stderr:
            response_parts.append(f"**Error:**\n```\n{stderr.decode('utf-8', errors='ignore').strip()}```")
        
        if not response_parts:
            response_parts.append(f"**Command executed, but no output. Exit Code: {process.returncode}**")
        
        final_response = "\n".join(response_parts)
        if len(final_response) > 4096: # Telegram message length limit
            with io.BytesIO(final_response.encode('utf-8')) as f:
                f.name = "output.txt"
                await client.send_document(
                    chat_id=message.chat.id,
                    document=f,
                    caption=f"`Output for {command}`"
                )
            await message.delete()
        else:
            await message.edit(final_response)
        
        logger.info(f"Exec successful: {command}, exit code: {process.returncode}")

    except Exception as e:
        logger.error(f"Error in exec command for command: '{command}': {e}", exc_info=True)
        await message.edit(f"**Error executing shell command:**\n`{type(e).__name__}: {e}`")

# -------------------------------------------------------------------------
# Command: .logs - Sends bot's log file.
# -------------------------------------------------------------------------
@app.on_message(filters.me & filters.command("logs", prefixes=COMMAND_PREFIX))
async def logs_command_handler(client: Client, message: Message):
    """
    Handles the .logs command to send the userbot's log file to the chat.
    """
    logger.info(f"Command {COMMAND_PREFIX}logs executed by user {message.from_user.id}.")
    log_file_path = "userbot.log"
    if os.path.exists(log_file_path):
        try:
            await client.send_document(
                chat_id=message.chat.id,
                document=log_file_path,
                caption="**Your userbot's log file:**"
            )
            await message.delete() # Delete the command message after sending logs
            logger.info("Log file successfully sent.")
        except Exception as e:
            logger.error(f"Error sending log file: {e}", exc_info=True)
            await message.edit(f"Error sending log file: `{e}`")
    else:
        await message.edit("`Log file not found.`")
        logger.warning("Log file 'userbot.log' does not exist.")

# -------------------------------------------------------------------------
# Command: .restart - Restarts the userbot. (Requires external management like systemd)
# -------------------------------------------------------------------------
@app.on_message(filters.me & filters.command("restart", prefixes=COMMAND_PREFIX))
async def restart_command_handler(client: Client, message: Message):
    """
    Handles the .restart command. Stops the bot process, expecting an external
    process manager (like systemd or a simple shell script) to restart it.
    """
    logger.warning(f"Command {COMMAND_PREFIX}restart executed by user {message.from_user.id}.")
    await message.edit("`Restarting bot... Please wait.`")
    try:
        await app.stop() # This will raise an exception during normal shutdown
        logger.info("Bot stopped for restart.")
        # os.execv(sys.executable, ['python'] + sys.argv) # This would restart in the same process
        # For Pyrogram, a clean stop and external restart is safer.
    except Exception as e:
        logger.error(f"Error during restart sequence: {e}", exc_info=True)
        await message.edit(f"`Restart initiated but encountered an error: {e}`")
    sys.exit(0) # Exit the process, relying on systemd/supervisor to restart


# =========================================================================
# SECTION 6: IMPLEMENTATION OF TEXT MANIPULATION COMMANDS
# Commands focused on altering or processing text input.
# =========================================================================

# -------------------------------------------------------------------------
# Command: .tr - Translates text.
# -------------------------------------------------------------------------
@app.on_message(filters.me & filters.command("tr", prefixes=COMMAND_PREFIX))
async def translate_command_handler(client: Client, message: Message):
    """
    Handles the .tr command for text translation.
    Supports auto-detection of source language and a specific target language.
    """
    logger.info(f"Command {COMMAND_PREFIX}tr executed by user {message.from_user.id}.")
    args = message.command
    
    if len(args) < 2:
        await message.edit(f"`Usage: {COMMAND_PREFIX}tr [target_lang_code] [text/reply]`\n"
                           f"`Example: {COMMAND_PREFIX}tr en سلام`")
        return

    target_lang_code = args[1].lower()
    text_to_translate = " ".join(args[2:])

    if not text_to_translate and message.reply_to_message and message.reply_to_message.text:
        text_to_translate = message.reply_to_message.text
    elif not text_to_translate:
        await message.edit(f"`Please provide text to translate or reply to a message.`")
        return

    if target_lang_code not in LANGUAGES:
        await message.edit(f"`Invalid language code '{target_lang_code}'. Please provide a valid ISO 639-1 code.`\n"
                           f"`You can search 'ISO 639-1 language codes' on Google.`")
        return

    await message.edit("`Translating... 🌐`")
    try:
        translated_obj = translator.translate(text_to_translate, dest=target_lang_code)
        
        if translated_obj and translated_obj.text:
            source_lang_name = LANGUAGES.get(translated_obj.src, translated_obj.src).capitalize()
            target_lang_name = LANGUAGES.get(target_lang_code, target_lang_code).capitalize()
            
            response_text = (
                f"**Translated from {source_lang_name} to {target_lang_name}:**\n"
                f"```\n{translated_obj.text}```\n"
                f"**Original Text ({source_lang_name}):**\n"
                f"```\n{text_to_translate}```"
            )
            await message.edit(response_text)
            logger.info(f"Translation successful: '{text_to_translate}' to '{target_lang_code}' -> '{translated_obj.text}'")
        else:
            await message.edit("`Error translating text. No translation found.`")
            logger.warning(f"Translation API returned no text for: '{text_to_translate}'")
    except Exception as e:
        logger.error(f"Error in translate command: {e}", exc_info=True)
        await message.edit(f"Error translating: `{e}`")

# -------------------------------------------------------------------------
# Command: .ud - Urban Dictionary lookup.
# -------------------------------------------------------------------------
@app.on_message(filters.me & filters.command("ud", prefixes=COMMAND_PREFIX))
async def ud_command_handler(client: Client, message: Message):
    """
    Handles the .ud command to search Urban Dictionary for a term.
    """
    logger.info(f"Command {COMMAND_PREFIX}ud executed by user {message.from_user.id}.")
    term = await extract_arg(message)
    if not term:
        await message.edit(f"`Please provide a word to search on Urban Dictionary! (Example: {COMMAND_PREFIX}ud bruh)`")
        return
    
    await message.edit(f"`Searching '{term}' on Urban Dictionary... 📚`")
    async with aiohttp.ClientSession() as session:
        json_data = await http_get_json(URBAN_DICTIONARY_API_URL, session, params={'term': term})
        
        if json_data and json_data.get('list'):
            definitions = json_data['list']
            if definitions:
                first_def = definitions[0]
                word = first_def.get('word', 'N/A')
                definition = first_def.get('definition', 'No definition available.')
                example = first_def.get('example', 'No example available.')
                
                # Truncate if too long
                definition = (definition[:500] + '...') if len(definition) > 500 else definition
                example = (example[:300] + '...') if len(example) > 300 else example

                response_text = (
                    f"**📚 Urban Dictionary Definition for '{word}':**\n\n"
                    f"**Definition:**\n`{definition}`\n\n"
                    f"**Example:**\n`{example}`\n\n"
                    f"[🔗 View on Urban Dictionary](https://www.urbandictionary.com/define.php?term={word.replace(' ', '%20')})"
                )
                await message.edit(response_text)
                logger.info(f"Urban Dictionary lookup successful for '{term}'.")
                return
    
    await message.edit(f"`No definition found for '{term}' on Urban Dictionary.`")
    logger.warning(f"Urban Dictionary lookup failed for '{term}'.")

# -------------------------------------------------------------------------
# Command: .reverse - Reverses input text.
# -------------------------------------------------------------------------
@app.on_message(filters.me & filters.command("reverse", prefixes=COMMAND_PREFIX))
async def reverse_command_handler(client: Client, message: Message):
    """
    Handles the .reverse command to reverse the input text.
    """
    logger.info(f"Command {COMMAND_PREFIX}reverse executed by user {message.from_user.id}.")
    text_to_reverse = await extract_arg(message)
    if not text_to_reverse and message.reply_to_message and message.reply_to_message.text:
        text_to_reverse = message.reply_to_message.text
    elif not text_to_reverse:
        await message.edit(f"`Please provide text to reverse or reply to a message.`")
        return
    
    try:
        reversed_text = text_to_reverse[::-1]
        await message.edit(f"**Reversed text:**\n`{reversed_text}`")
        logger.info(f"Text reversed: '{text_to_reverse}' -> '{reversed_text}'")
    except Exception as e:
        logger.error(f"Error in reverse command: {e}", exc_info=True)
        await message.edit(f"Error reversing text: `{e}`")

# -------------------------------------------------------------------------
# Command: .owo - Converts text to 'OwO' language.
# -------------------------------------------------------------------------
@app.on_message(filters.me & filters.command("owo", prefixes=COMMAND_PREFIX))
async def owo_command_handler(client: Client, message: Message):
    """
    Handles the .owo command to convert text to 'OwO' language.
    """
    logger.info(f"Command {COMMAND_PREFIX}owo executed by user {message.from_user.id}.")
    text = await extract_arg(message)
    if not text and message.reply_to_message and message.reply_to_message.text:
        text = message.reply_to_message.text
    elif not text:
        await message.edit(f"`Please provide text to 'OwOify' or reply to a message.`")
        return

    def owoify(text_input: str) -> str:
        replacements = {
            'l': 'w', 'r': 'w', 'L': 'W', 'R': 'W',
            'na': 'nya', 'ne': 'nye', 'ni': 'nyi', 'no': 'nyo', 'nu': 'nyu',
            'Na': 'Nya', 'Ne': 'Nye', 'Ni': 'Nyi', 'No': 'Nyo', 'Nu': 'Nyu'
        }
        for k, v in replacements.items():
            text_input = text_input.replace(k, v)
        emotes = [" OwO", " UwU", " >w<", " owo", " uwu", " >w<", " (´・ω・`)", " ;3"]
        return text_input + random.choice(emotes)

    try:
        owo_text = owoify(text)
        await message.edit(f"**OwOified:**\n`{owo_text}`")
        logger.info(f"OwOified text: '{text}' -> '{owo_text}'")
    except Exception as e:
        logger.error(f"Error in OwO command: {e}", exc_info=True)
        await message.edit(f"Error OwOifying text: `{e}`")

# -------------------------------------------------------------------------
# Command: .mock - Converts text to "mOcKiNg SpOnGeBoB" style.
# -------------------------------------------------------------------------
@app.on_message(filters.me & filters.command("mock", prefixes=COMMAND_PREFIX))
async def mock_command_handler(client: Client, message: Message):
    """
    Handles the .mock command to convert text to alternating case (Mocking Spongebob).
    """
    logger.info(f"Command {COMMAND_PREFIX}mock executed by user {message.from_user.id}.")
    text = await extract_arg(message)
    if not text and message.reply_to_message and message.reply_to_message.text:
        text = message.reply_to_message.text
    elif not text:
        await message.edit(f"`Please provide text to 'mock' or reply to a message.`")
        return

    def mock_text(text_input: str) -> str:
        mocked = ""
        for i, char in enumerate(text_input):
            if char.isalpha():
                if i % 2 == 0:
                    mocked += char.lower()
                else:
                    mocked += char.upper()
            else:
                mocked += char
        return mocked

    try:
        mocked_text = mock_text(text)
        await message.edit(f"**MoCkEd:**\n`{mocked_text}`")
        logger.info(f"Mocked text: '{text}' -> '{mocked_text}'")
    except Exception as e:
        logger.error(f"Error in Mock command: {e}", exc_info=True)
        await message.edit(f"Error mocking text: `{e}`")

# -------------------------------------------------------------------------
# Command: .ascii - ASCII Art generator (Simulated/Placeholder)
# -------------------------------------------------------------------------
@app.on_message(filters.me & filters.command("ascii", prefixes=COMMAND_PREFIX))
async def ascii_command_handler(client: Client, message: Message):
    """
    Handles the .ascii command to convert text to ASCII Art.
    Currently a placeholder that can be extended with external APIs or libraries.
    """
    logger.info(f"Command {COMMAND_PREFIX}ascii executed by user {message.from_user.id}.")
    text = await extract_arg(message)
    if not text and message.reply_to_message and message.reply_to_message.text:
        text = message.reply_to_message.text
    elif not text:
        await message.edit(f"`Please provide text to convert to ASCII Art or reply to a message.`")
        return

    await message.edit(f"`Converting '{text}' to ASCII Art... (Simulated via an API)`")
    try:
        # Placeholder for an actual ASCII art API call or local library integration
        # For example, using a free API:
        # async with aiohttp.ClientSession() as session:
        #     api_url = f"https://artii.herokuapp.com/make?text={requests.utils.quote(text)}"
        #     async with session.get(api_url) as response:
        #         if response.status == 200:
        #             ascii_art = await response.text()
        #             await message.edit(f"```\n{ascii_art}```")
        #             logger.info(f"ASCII art generated for '{text}'.")
        #             return
        #         else:
        #             await message.edit(f"`Failed to generate ASCII art (API Error {response.status}).`")
        
        # Fallback / Example: simple local transformation
        # For proper ASCII art, external libraries like `art` or `pyfiglet` (as shown below) are needed.
        processed_text = ""
        for char in text:
            if char.isalpha():
                processed_text += chr(ord(char) + 0xFEE0) # Full-width characters as a simple visual trick
            else:
                processed_text += char

        await message.edit(f"**ASCII Art (simulated):**\n`{processed_text}`\n"
                           f"*Hint: For real ASCII art, a dedicated API or library is needed.*")
        logger.info(f"ASCII art (simulated) generated for '{text}'.")

    except Exception as e:
        logger.error(f"Error in ASCII command: {e}", exc_info=True)
        await message.edit(f"Error generating ASCII art: `{e}`")

# -------------------------------------------------------------------------
# Command: .figlet - Figlet text generator.
# -------------------------------------------------------------------------
@app.on_message(filters.me & filters.command("figlet", prefixes=COMMAND_PREFIX))
async def figlet_command_handler(client: Client, message: Message):
    """
    Handles the .figlet command to convert text into large ASCII art (Figlet style).
    Requires the `pyfiglet` library.
    """
    logger.info(f"Command {COMMAND_PREFIX}figlet executed by user {message.from_user.id}.")
    text = await extract_arg(message)
    if not text and message.reply_to_message and message.reply_to_message.text:
        text = message.reply_to_message.text
    elif not text:
        await message.edit(f"`Please provide text to convert to Figlet or reply to a message.`")
        return
    
    await message.edit(f"`Generating Figlet for '{text}'...`")
    try:
        figlet_text = pyfiglet.figlet_format(text)
        if len(figlet_text) > 4096:
            # If too long, send as a document
            with io.BytesIO(figlet_text.encode('utf-8')) as f:
                f.name = "figlet.txt"
                await client.send_document(
                    chat_id=message.chat.id,
                    document=f,
                    caption=f"**Figlet for:** `{text}`"
                )
            await message.delete()
        else:
            await message.edit(f"```\n{figlet_text}```")
        logger.info(f"Figlet generated for '{text}'.")
    except Exception as e:
        logger.error(f"Error in figlet command: {e}", exc_info=True)
        await message.edit(f"Error generating Figlet text: `{e}`")

# -------------------------------------------------------------------------
# Command: .quote - Random quote generator.
# -------------------------------------------------------------------------
@app.on_message(filters.me & filters.command("quote", prefixes=COMMAND_PREFIX))
async def quote_command_handler(client: Client, message: Message):
    """
    Handles the .quote command to fetch and display a random inspirational quote.
    Uses an external API (e.g., ZenQuotes).
    """
    logger.info(f"Command {COMMAND_PREFIX}quote executed by user {message.from_user.id}.")
    await message.edit("`Fetching a random quote... 💬`")
    async with aiohttp.ClientSession() as session:
        # Example API: ZenQuotes (free, no API key needed)
        json_data = await http_get_json("https://zenquotes.io/api/random", session)
        
        if json_data and isinstance(json_data, list) and json_data:
            quote_data = json_data[0]
            quote_text = quote_data.get('q', 'No quote text.')
            author = quote_data.get('a', 'Unknown')
            
            response_text = (
                f"**💭 Random Quote:**\n"
                f"```\n{quote_text}```\n"
                f"**— {author}**"
            )
            await message.edit(response_text)
            logger.info(f"Random quote fetched: '{quote_text}' by {author}.")
            return
    
    await message.edit("`Failed to fetch a random quote.`")
    logger.warning("Failed to fetch random quote from API.")

# -------------------------------------------------------------------------
# Command: .spell - Spell checker.
# -------------------------------------------------------------------------
@app.on_message(filters.me & filters.command("spell", prefixes=COMMAND_PREFIX))
async def spell_command_handler(client: Client, message: Message):
    """
    Handles the .spell command to correct the spelling of a given word.
    Requires the `pyspellchecker` library.
    """
    logger.info(f"Command {COMMAND_PREFIX}spell executed by user {message.from_user.id}.")
    text = await extract_arg(message)
    if not text:
        await message.edit(f"`Please provide a word for spell check.`")
        return
    
    await message.edit(f"`Checking spelling for '{text}'...`")
    try:
        corrected_word = spell.correction(text)
        if corrected_word and corrected_word.lower() != text.lower():
            response_text = f"**Possible correction for '{text}':** `{corrected_word}`"
        else:
            response_text = f"**'{text}' seems to be spelled correctly.**"
        
        await message.edit(response_text)
        logger.info(f"Spell check for '{text}': '{corrected_word}'.")
    except Exception as e:
        logger.error(f"Error in spell command: {e}", exc_info=True)
        await message.edit(f"Error during spell check: `{e}`")

# -------------------------------------------------------------------------
# Command: .base64e / .base64d - Base64 encode/decode.
# -------------------------------------------------------------------------
@app.on_message(filters.me & filters.command(["base64e", "b64e"], prefixes=COMMAND_PREFIX))
async def base64_encode_handler(client: Client, message: Message):
    """
    Handles the .base64e command to encode text to Base64.
    """
    logger.info(f"Command {COMMAND_PREFIX}base64e executed by user {message.from_user.id}.")
    text = await extract_arg(message)
    if not text and message.reply_to_message and message.reply_to_message.text:
        text = message.reply_to_message.text
    elif not text:
        await message.edit(f"`Please provide text to encode.`")
        return
    
    try:
        encoded_text = base64.b64encode(text.encode('utf-8')).decode('utf-8')
        await message.edit(f"**Base64 Encoded:**\n`{encoded_text}`")
        logger.info(f"Text Base64 encoded.")
    except Exception as e:
        logger.error(f"Error in base64e command: {e}", exc_info=True)
        await message.edit(f"Error encoding to Base64: `{e}`")

@app.on_message(filters.me & filters.command(["base64d", "b64d"], prefixes=COMMAND_PREFIX))
async def base64_decode_handler(client: Client, message: Message):
    """
    Handles the .base64d command to decode Base64 text.
    """
    logger.info(f"Command {COMMAND_PREFIX}base64d executed by user {message.from_user.id}.")
    text = await extract_arg(message)
    if not text and message.reply_to_message and message.reply_to_message.text:
        text = message.reply_to_message.text
    elif not text:
        await message.edit(f"`Please provide text to decode.`")
        return
    
    try:
        decoded_text = base64.b64decode(text.encode('utf-8')).decode('utf-8')
        await message.edit(f"**Base64 Decoded:**\n`{decoded_text}`")
        logger.info(f"Text Base64 decoded.")
    except Exception as e:
        logger.error(f"Error in base64d command: {e}", exc_info=True)
        await message.edit(f"Error decoding Base64: `{e}`")

# -------------------------------------------------------------------------
# Commands: .bold / .italic / .code / .strike - Text formatting.
# -------------------------------------------------------------------------
async def apply_text_format(message: Message, format_char: str):
    """Helper to apply basic markdown formatting."""
    text = await extract_arg(message)
    if not text and message.reply_to_message and message.reply_to_message.text:
        text = message.reply_to_message.text
    elif not text:
        await message.edit(f"`Please provide text to format or reply to a message.`")
        return
    
    formatted_text = f"{format_char}{text}{format_char}"
    await message.edit(formatted_text)
    logger.info(f"Applied format '{format_char}' to text.")

@app.on_message(filters.me & filters.command("bold", prefixes=COMMAND_PREFIX))
async def bold_command_handler(client: Client, message: Message):
    """Applies bold formatting to text."""
    await apply_text_format(message, "**")

@app.on_message(filters.me & filters.command("italic", prefixes=COMMAND_PREFIX))
async def italic_command_handler(client: Client, message: Message):
    """Applies italic formatting to text."""
    await apply_text_format(message, "__") # Or * for italic

@app.on_message(filters.me & filters.command("code", prefixes=COMMAND_PREFIX))
async def code_command_handler(client: Client, message: Message):
    """Applies code block formatting to text."""
    await apply_text_format(message, "```")

@app.on_message(filters.me & filters.command("strike", prefixes=COMMAND_PREFIX))
async def strike_command_handler(client: Client, message: Message):
    """Applies strikethrough formatting to text."""
    await apply_text_format(message, "~~")

# =========================================================================
# SECTION 7: IMPLEMENTATION OF MEDIA & FUN COMMANDS
# Commands related to media, entertainment, and playful interactions.
# =========================================================================

# -------------------------------------------------------------------------
# Command: .carbon - Code-to-image (Simulated/Placeholder)
# -------------------------------------------------------------------------
@app.on_message(filters.me & filters.command("carbon", prefixes=COMMAND_PREFIX))
async def carbon_command_handler(client: Client, message: Message):
    """
    Handles the .carbon command to convert code into a stylized image (Carbon.sh style).
    This is a simulated command, as direct integration with Carbon.sh API or
    headless browser automation is complex and resource-intensive for a userbot.
    """
    logger.info(f"Command {COMMAND_PREFIX}carbon executed by user {message.from_user.id}.")
    code_text = await extract_arg(message)
    if not code_text and message.reply_to_message and message.reply_to_message.text:
        code_text = message.reply_to_message.text
    elif not code_text:
        await message.edit(f"`Please provide code to convert to a Carbon image or reply to a message.`")
        return
    
    await message.edit(f"`Generating Carbon image for your code... (Simulated)`")
    try:
        # In a real implementation, you would use:
        # 1. A dedicated Carbon API if available.
        # 2. Selenium/Playwright with a headless browser to visit carbon.sh, paste code,
        #    customize settings, and take a screenshot. This requires browser installation
        #    and significant resources.
        
        # For simulation, we'll create a dummy image or format code neatly.
        # Here's a very basic image generation example using PIL, not a true Carbon.sh output.
        
        # Create a simple image (e.g., black background, white text)
        img_width = 800
        img_height = 400
        img = Image.new('RGB', (img_width, img_height), color = (45, 45, 45)) # Dark background
        d = ImageDraw.Draw(img)

        try:
            # Try to load a font for better appearance
            font = ImageFont.truetype("arial.ttf", 20) # You might need to specify a path like "/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf"
        except IOError:
            font = ImageFont.load_default() # Fallback to default if font not found
        
        lines = code_text.split('\n')
        y_offset = 20
        for line in lines:
            d.text((30, y_offset), line, font=font, fill=(255, 255, 255))
            y_offset += 25
            if y_offset > img_height - 30: # Prevent text overflow
                break
        
        # Save to in-memory bytes
        img_byte_arr = io.BytesIO()
        img.save(img_byte_arr, format='PNG')
        img_byte_arr.seek(0)
        
        await client.send_photo(
            chat_id=message.chat.id,
            photo=img_byte_arr,
            caption=f"**Carbonized Code (Simulated):**\n`{code_text[:100]}...`"
        )
        await message.delete()
        logger.info(f"Simulated Carbon image sent for code: '{code_text[:50]}...'.")

    except Exception as e:
        logger.error(f"Error in carbon command (simulated): {e}", exc_info=True)
        await message.edit(f"Error generating Carbon image: `{e}`\n"
                           f"*Note: This command is simulated and needs actual integration for full functionality.*")

# -------------------------------------------------------------------------
# Command: .ss - Website screenshot (Simulated/Placeholder)
# -------------------------------------------------------------------------
@app.on_message(filters.me & filters.command("ss", prefixes=COMMAND_PREFIX))
async def screenshot_command_handler(client: Client, message: Message):
    """
    Handles the .ss command to take a screenshot of a website.
    This is a simulated command, as direct screenshot generation requires
    a headless browser environment or a dedicated screenshot API.
    """
    logger.info(f"Command {COMMAND_PREFIX}ss executed by user {message.from_user.id}.")
    url = await extract_arg(message)
    if not url:
        await message.edit(f"`Please provide a URL for the screenshot! (Example: {COMMAND_PREFIX}ss https://google.com)`")
        return
    if not (url.startswith("http://") or url.startswith("https://")):
        url = "http://" + url # Assume http if no protocol specified

    await message.edit(f"`Taking screenshot of '{url}'... (Simulated)`")
    try:
        # In a real implementation, you would use:
        # 1. A public screenshot API (e.g., screenshotone.com, urlbox.io - usually paid).
        # 2. Selenium/Playwright with a headless browser to open the URL and take a screenshot.
        #    This requires browser installation (e.g., Chromium) and significant resources.

        # For simulation, we'll create a dummy image.
        img = Image.new('RGB', (1024, 768), color = (50, 50, 150)) # Blueish background
        d = ImageDraw.Draw(img)
        try:
            font = ImageFont.truetype("arial.ttf", 30)
        except IOError:
            font = ImageFont.load_default()

        d.text((50, 300), f"Screenshot of: {url}", font=font, fill=(255, 255, 255))
        d.text((50, 350), "(Simulated - requires external API/browser)", font=font, fill=(200, 200, 200))

        img_byte_arr = io.BytesIO()
        img.save(img_byte_arr, format='PNG')
        img_byte_arr.seek(0)
        
        await client.send_photo(
            chat_id=message.chat.id,
            photo=img_byte_arr,
            caption=f"**Screenshot (Simulated):** `{url}`"
        )
        await message.delete()
        logger.info(f"Simulated screenshot sent for URL: '{url}'.")

    except Exception as e:
        logger.error(f"Error in screenshot command (simulated): {e}", exc_info=True)
        await message.edit(f"Error generating screenshot: `{e}`\n"
                           f"*Note: This command is simulated and needs actual integration for full functionality.*")

# -------------------------------------------------------------------------
# Command: .qr - QR Code Generator.
# -------------------------------------------------------------------------
@app.on_message(filters.me & filters.command("qr", prefixes=COMMAND_PREFIX))
async def qr_command_handler(client: Client, message: Message):
    """
    Generates a QR code for the given text.
    Requires `qrcode` and `Pillow` libraries.
    """
    logger.info(f"Command {COMMAND_PREFIX}qr executed by user {message.from_user.id}.")
    text = await extract_arg(message)
    if not text:
        await message.edit(f"`Please provide text to convert to a QR code! (Example: {COMMAND_PREFIX}qr Hello World)`")
        return
    
    await message.edit(f"`Generating QR code for '{text[:50]}...'...`")
    try:
        qr = qrcode.QRCode(
            version=1,
            error_correction=qrcode.constants.ERROR_CORRECT_H, # High error correction
            box_size=10,
            border=4,
        )
        qr.add_data(text)
        qr.make(fit=True)

        img = qr.make_image(fill_color="black", back_color="white")
        
        # Save to in-memory bytes
        img_byte_arr = io.BytesIO()
        img.save(img_byte_arr, format='PNG')
        img_byte_arr.seek(0)
        
        await client.send_photo(
            chat_id=message.chat.id,
            photo=img_byte_arr,
            caption=f"**QR Code for:** `{text[:200]}`" # Truncate caption for long texts
        )
        await message.delete() # Delete the command message
        logger.info(f"QR code generated and sent for '{text[:50]}...'.")
    except ImportError:
        await message.edit("`This command requires 'qrcode' and 'Pillow' libraries. Please install them: pip install qrcode Pillow`")
        logger.error("qrcode or Pillow not installed for QR command.")
    except Exception as e:
        logger.error(f"Error in QR command: {e}", exc_info=True)
        await message.edit(f"Error generating QR code: `{e}`")

# -------------------------------------------------------------------------
# Command: .meme - Random meme generator.
# -------------------------------------------------------------------------
@app.on_message(filters.me & filters.command("meme", prefixes=COMMAND_PREFIX))
async def meme_command_handler(client: Client, message: Message):
    """
    Handles the .meme command to fetch and send a random meme from an API.
    """
    logger.info(f"Command {COMMAND_PREFIX}meme executed by user {message.from_user.id}.")
    await message.edit("`Fetching a random meme... 🤣`")
    async with aiohttp.ClientSession() as session:
        json_data = await http_get_json(MEME_API_URL, session)
        
        if json_data and json_data.get('url'):
            meme_url = json_data['url']
            post_link = json_data.get('postLink', 'N/A')
            title = json_data.get('title', 'Random Meme')
            subreddit = json_data.get('subreddit', 'N/A')
            
            caption = (
                f"**🤣 Random Meme:**\n"
                f"**Title:** `{title}`\n"
                f"**Subreddit:** `r/{subreddit}`\n"
                f"[🔗 Source]({post_link})"
            )
            
            try:
                # Telegram can send photos from URL directly
                await client.send_photo(
                    chat_id=message.chat.id,
                    photo=meme_url,
                    caption=caption
                )
                await message.delete()
                logger.info(f"Meme sent from URL: {meme_url}.")
            except Exception as e:
                logger.error(f"Error sending meme from URL {meme_url}: {e}", exc_info=True)
                await message.edit(f"`Failed to send meme. Error: {e}`")
            return
    
    await message.edit("`Failed to fetch a random meme.`")
    logger.warning("Meme API did not return a valid meme URL.")

# -------------------------------------------------------------------------
# Command: .gif - GIF search and send.
# -------------------------------------------------------------------------
@app.on_message(filters.me & filters.command("gif", prefixes=COMMAND_PREFIX))
async def gif_command_handler(client: Client, message: Message):
    """
    Handles the .gif command to search for GIFs using a Tenor API (or similar)
    and send the first result.
    """
    logger.info(f"Command {COMMAND_PREFIX}gif executed by user {message.from_user.id}.")
    query = await extract_arg(message)
    if not query:
        await message.edit(f"`Please provide a query for GIF search! (Example: {COMMAND_PREFIX}gif funny cats)`")
        return

    if not GIF_API_KEY:
        await message.edit("`TENOR_API_KEY is not set in your .env file. Cannot search GIFs.`")
        logger.warning("TENOR_API_KEY is missing.")
        return

    await message.edit(f"`Searching for GIFs related to '{query}'... 🖼️`")
    async with aiohttp.ClientSession() as session:
        tenor_url = TENOR_API_URL.format(query=requests.utils.quote(query), api_key=GIF_API_KEY, limit=1)
        json_data = await http_get_json(tenor_url, session)
        
        if json_data and json_data.get('results'):
            gif_data = json_data['results']
            # Tenor API often returns different media types, pick a relevant one
            media_info = gif_data['media']['gif'] # Standard GIF format
            gif_url = media_info['url']
            
            try:
                await client.send_animation(
                    chat_id=message.chat.id,
                    animation=gif_url,
                    caption=f"**GIF for:** `{query}`"
                )
                await message.delete()
                logger.info(f"GIF sent for query '{query}': {gif_url}.")
            except Exception as e:
                logger.error(f"Error sending GIF {gif_url}: {e}", exc_info=True)
                await message.edit(f"`Failed to send GIF. Error: {e}`")
            return
    
    await message.edit(f"`No GIFs found for '{query}'.`")
    logger.warning(f"GIF search failed for query '{query}'.")

# -------------------------------------------------------------------------
# Command: .sticker - Converts a photo to a Telegram sticker.
# -------------------------------------------------------------------------
@app.on_message(filters.me & filters.command("sticker", prefixes=COMMAND_PREFIX))
async def sticker_command_handler(client: Client, message: Message):
    """
    Handles the .sticker command to convert a replied photo into a Telegram sticker.
    Telegram sticker sets require a special process; this command will simply convert
    an image to a .webp format, which Telegram accepts as a sticker.
    """
    logger.info(f"Command {COMMAND_PREFIX}sticker executed by user {message.from_user.id}.")
    if not message.reply_to_message or not message.reply_to_message.photo:
        await message.edit(f"`Please reply to a photo to convert it into a sticker.`")
        return

    await message.edit("`Converting photo to sticker... ✨`")
    try:
        photo = message.reply_to_message.photo
        # Download the photo
        photo_path = await client.download_media(photo)
        
        with Image.open(photo_path) as img:
            # Resize image for sticker (512x512, with one side exactly 512px)
            if img.width > img.height:
                new_width = 512
                new_height = int(img.height * (new_width / img.width))
            else:
                new_height = 512
                new_width = int(img.width * (new_height / img.height))
            
            img = img.resize((new_width, new_height), Image.LANCZOS)
            
            # Stickers usually have transparent backgrounds, but PIL converts to white by default
            # For simplicity, we'll just convert to WEBP
            
            # Save to in-memory bytes as WEBP
            img_byte_arr = io.BytesIO()
            img.save(img_byte_arr, format='WEBP')
            img_byte_arr.seek(0)
            
            await client.send_sticker(
                chat_id=message.chat.id,
                sticker=img_byte_arr
            )
            await message.delete()
            logger.info(f"Photo converted to sticker and sent.")
        
        # Clean up downloaded file
        os.remove(photo_path)
    except Exception as e:
        logger.error(f"Error in sticker command: {e}", exc_info=True)
        await message.edit(f"Error converting to sticker: `{e}`")

# -------------------------------------------------------------------------
# Command: .dice - Rolls a dice.
# -------------------------------------------------------------------------
@app.on_message(filters.me & filters.command("dice", prefixes=COMMAND_PREFIX))
async def dice_command_handler(client: Client, message: Message):
    """
    Handles the .dice command to simulate a dice roll.
    """
    logger.info(f"Command {COMMAND_PREFIX}dice executed by user {message.from_user.id}.")
    await message.edit("`Rolling the dice... 🎲`")
    try:
        roll = random.randint(1, 6)
        emoji_map = {1: "1️⃣", 2: "2️⃣", 3: "3️⃣", 4: "4️⃣", 5: "5️⃣", 6: "6️⃣"}
        await message.edit(f"**You rolled:** {emoji_map.get(roll, str(roll))} (Value: `{roll}`)")
        logger.info(f"Dice rolled, result: {roll}.")
    except Exception as e:
        logger.error(f"Error in dice command: {e}", exc_info=True)
        await message.edit(f"Error rolling dice: `{e}`")

# -------------------------------------------------------------------------
# Command: .coin - Flips a coin.
# -------------------------------------------------------------------------
@app.on_message(filters.me & filters.command("coin", prefixes=COMMAND_PREFIX))
async def coin_command_handler(client: Client, message: Message):
    """
    Handles the .coin command to simulate a coin flip.
    """
    logger.info(f"Command {COMMAND_PREFIX}coin executed by user {message.from_user.id}.")
    await message.edit("`Flipping a coin... 🪙`")
    try:
        flip = random.choice(["Heads", "Tails"])
        emoji = "👑" if flip == "Heads" else "⚫"
        await message.edit(f"**Coin landed on:** `{flip}` {emoji}")
        logger.info(f"Coin flipped, result: {flip}.")
    except Exception as e:
        logger.error(f"Error in coin command: {e}", exc_info=True)
        await message.edit(f"Error flipping coin: `{e}`")

# -------------------------------------------------------------------------
# Command: .choose - Randomly chooses from options.
# -------------------------------------------------------------------------
@app.on_message(filters.me & filters.command("choose", prefixes=COMMAND_PREFIX))
async def choose_command_handler(client: Client, message: Message):
    """
    Handles the .choose command to randomly select an option from a provided list.
    Options are separated by semicolons.
    """
    logger.info(f"Command {COMMAND_PREFIX}choose executed by user {message.from_user.id}.")
    options_str = await extract_arg(message)
    if not options_str:
        await message.edit(f"`Please provide options separated by semicolons. (Example: {COMMAND_PREFIX}choose Pizza; Burger; Pasta)`")
        return
    
    options = [opt.strip() for opt in options_str.split(';') if opt.strip()]
    if not options:
        await message.edit(f"`No valid options provided. Please separate options with semicolons.`")
        return
    
    try:
        chosen = random.choice(options)
        await message.edit(f"**I choose:** `{chosen}` 🤔")
        logger.info(f"Chosen from options '{options_str}': '{chosen}'.")
    except Exception as e:
        logger.error(f"Error in choose command: {e}", exc_info=True)
        await message.edit(f"Error choosing option: `{e}`")

# -------------------------------------------------------------------------
# Command: .shrug - Sends shrug emoticon.
# -------------------------------------------------------------------------
@app.on_message(filters.me & filters.command("shrug", prefixes=COMMAND_PREFIX))
async def shrug_command_handler(client: Client, message: Message):
    """
    Sends the shrug emoticon.
    """
    logger.info(f"Command {COMMAND_PREFIX}shrug executed by user {message.from_user.id}.")
    try:
        await message.edit("¯\\_(ツ)_/¯")
        logger.info("Shrug emoticon sent.")
    except Exception as e:
        logger.error(f"Error in shrug command: {e}", exc_info=True)
        await message.edit(f"Error sending shrug: `{e}`")

# -------------------------------------------------------------------------
# Command: .table - Sends table flip emoticon.
# -------------------------------------------------------------------------
@app.on_message(filters.me & filters.command("table", prefixes=COMMAND_PREFIX))
async def table_command_handler(client: Client, message: Message):
    """
    Sends the table flip emoticon.
    """
    logger.info(f"Command {COMMAND_PREFIX}table executed by user {message.from_user.id}.")
    try:
        await message.edit("(╯°□°）╯︵ ┻━┻")
        logger.info("Table flip emoticon sent.")
    except Exception as e:
        logger.error(f"Error in table command: {e}", exc_info=True)
        await message.edit(f"Error sending table flip: `{e}`")

# -------------------------------------------------------------------------
# Command: .lovecalc - Calculates compatibility between two names.
# -------------------------------------------------------------------------
@app.on_message(filters.me & filters.command("lovecalc", prefixes=COMMAND_PREFIX))
async def lovecalc_command_handler(client: Client, message: Message):
    """
    Handles the .lovecalc command to simulate a love compatibility calculation.
    """
    logger.info(f"Command {COMMAND_PREFIX}lovecalc executed by user {message.from_user.id}.")
    args = message.command
    if len(args) < 3:
        await message.edit(f"`Usage: {COMMAND_PREFIX}lovecalc [Name1] [Name2]`")
        return

    name1 = args.lower()
    name2 = args.lower()

    # Simple deterministic "calculation" for demonstration
    combined_name = sorted(name1 + name2)
    score = sum(ord(c) for c in combined_name) % 101 # 0-100
    
    emoji = "💔" if score < 30 else ("❤️‍🩹" if score < 60 else "💖")

    await message.edit(f"**❤️ Love Compatibility:**\n"
                       f"• `{name1.capitalize()}` and `{name2.capitalize()}`\n"
                       f"• **Score:** `{score}%` {emoji}\n"
                       f"*(This is just for fun!)*")
    logger.info(f"Love calculation for {name1} and {name2} resulted in {score}%.")

# =========================================================================
# SECTION 8: IMPLEMENTATION OF INFORMATION & SEARCH COMMANDS
# Commands for retrieving various types of information and performing searches.
# =========================================================================

# -------------------------------------------------------------------------
# Command: .wiki - Wikipedia search.
# -------------------------------------------------------------------------
@app.on_message(filters.me & filters.command("wiki", prefixes=COMMAND_PREFIX))
async def wiki_command_handler(client: Client, message: Message):
    """
    Handles the .wiki command to search Wikipedia, preferring Farsi, then English.
    """
    logger.info(f"Command {COMMAND_PREFIX}wiki executed by user {message.from_user.id}.")
    query = await extract_arg(message)
    if not query:
        await message.edit(f"`Please provide a keyword to search on Wikipedia! (Example: {COMMAND_PREFIX}wiki Python)`")
        return

    await message.edit("`Searching Wikipedia... 🔍`")
    try:
        page_fa = wiki_wiki_fa.page(query)
        
        if page_fa.exists():
            summary = page_fa.summary
            summary = (summary[:700] + "...") if len(summary) > 700 else summary
            response_text = (
                f"**📚 Wikipedia (Farsi):**\n"
                f"**Title:** `{page_fa.title}`\n"
                f"**Summary:** ```\n{summary}```\n"
                f"**Link:** [Read More]({page_fa.fullurl})"
            )
            await message.edit(response_text)
            logger.info(f"Wikipedia (Farsi) search successful for '{query}'.")
        else:
            # If Farsi not found, try English
            page_en = wiki_wiki_en.page(query)
            if page_en.exists():
                summary = page_en.summary
                summary = (summary[:700] + "...") if len(summary) > 700 else summary
                response_text = (
                    f"**📚 Wikipedia (English):**\n"
                    f"**Title:** `{page_en.title}`\n"
                    f"**Summary:** ```\n{summary}```\n"
                    f"**Link:** [Read More]({page_en.fullurl})"
                )
                await message.edit(response_text)
                logger.info(f"Wikipedia (English) search successful for '{query}'.")
            else:
                await message.edit(f"`No results found for '{query}' on Wikipedia (Farsi or English).`")
                logger.warning(f"Wikipedia search failed for '{query}'.")

    except Exception as e:
        logger.error(f"Error in wiki command: {e}", exc_info=True)
        await message.edit(f"Error searching Wikipedia: `{e}`")

# -------------------------------------------------------------------------
# Command: .g - Google Search (Simulated/Placeholder for Custom Search API)
# -------------------------------------------------------------------------
@app.on_message(filters.me & filters.command("g", prefixes=COMMAND_PREFIX))
async def google_command_handler(client: Client, message: Message):
    """
    Handles the .g command for Google search.
    This implementation simulates a search or can be expanded with Google Custom Search API.
    """
    logger.info(f"Command {COMMAND_PREFIX}g executed by user {message.from_user.id}.")
    query = await extract_arg(message)
    if not query:
        await message.edit(f"`Please provide a query for Google search! (Example: {COMMAND_PREFIX}g Pyrogram)`")
        return

    await message.edit(f"`Searching Google for '{query}'... 🌐`")
    try:
        # Actual Google Custom Search API integration:
        # This requires GOOGLE_SEARCH_API_KEY and GOOGLE_CSE_ID
        if GOOGLE_SEARCH_API_KEY and GOOGLE_CSE_ID:
            search_url = "https://www.googleapis.com/customsearch/v1"
            params = {
                "key": GOOGLE_SEARCH_API_KEY,
                "cx": GOOGLE_CSE_ID,
                "q": query,
                "num": 3 # Number of results
            }
            async with aiohttp.ClientSession() as session:
                json_data = await http_get_json(search_url, session, params=params)

                if json_data and json_data.get('items'):
                    results = json_data['items']
                    response_text = f"**🌐 Google Search Results for '{query}':**\n\n"
                    for i, item in enumerate(results[:3]): # Limit to top 3
                        title = item.get('title', 'N/A')
                        link = item.get('link', '#')
                        snippet = item.get('snippet', 'No snippet available.')
                        snippet = (snippet[:150] + '...') if len(snippet) > 150 else snippet
                        response_text += f"**{i+1}. [{title}]({link})**\n`{snippet}`\n\n"
                    await message.edit(response_text)
                    logger.info(f"Google search successful for '{query}'.")
                    return
                else:
                    logger.warning(f"Google Search API returned no results for '{query}'.")
        
        # Fallback to direct search link if API keys are missing or no results
        search_link = f"https://www.google.com/search?q={requests.utils.quote(query)}"
        response_text = (
            f"**🌐 Google Search:**\n"
            f"**Query:** `{query}`\n"
            f"[🔗 Click here to search on Google]({search_link})\n\n"
            f"*Hint: For direct results, configure GOOGLE_SEARCH_API_KEY and GOOGLE_CSE_ID in .env.*"
        )
        await message.edit(response_text)
        logger.info(f"Google search link provided for '{query}'.")

    except Exception as e:
        logger.error(f"Error in Google search command: {e}", exc_info=True)
        await message.edit(f"Error performing Google search: `{e}`")

# -------------------------------------------------------------------------
# Command: .weather - OpenWeatherMap integration.
# -------------------------------------------------------------------------
@app.on_message(filters.me & filters.command("weather", prefixes=COMMAND_PREFIX))
async def weather_command_handler(client: Client, message: Message):
    """
    Handles the .weather command to fetch and display current weather information
    for a specified city using OpenWeatherMap API.
    """
    logger.info(f"Command {COMMAND_PREFIX}weather executed by user {message.from_user.id}.")
    city = await extract_arg(message)
    if not city:
        await message.edit(f"`Please enter a city name! (Example: {COMMAND_PREFIX}weather Tehran)`")
        return
    
    if not WEATHER_API_KEY:
        await message.edit("`WEATHER_API_KEY is not set in your .env file. Cannot fetch weather.`")
        logger.warning("WEATHER_API_KEY is missing.")
        return

    await message.edit(f"`Fetching weather for '{city}'... ☁️`")
    OPENWEATHER_URL = f"http://api.openweathermap.org/data/2.5/weather?q={city}&appid={WEATHER_API_KEY}&units=metric&lang=en"
    
    async with aiohttp.ClientSession() as session:
        json_data = await http_get_json(OPENWEATHER_URL, session)
        
        if json_data:
            main_weather = json_data['weather']['description']
            temp = json_data['main']['temp']
            feels_like = json_data['main']['feels_like']
            humidity = json_data['main']['humidity']
            wind_speed = json_data['wind']['speed']
            pressure = json_data['main']['pressure']
            visibility = json_data.get('visibility') # in meters
            
            response_text = (
                f"**☀️ Weather for {city.capitalize()}:**\n"
                f"▪️ **Condition:** `{main_weather.capitalize()}`\n"
                f"▪️ **Temperature:** `{temp}°C`\n"
                f"▪️ **Feels like:** `{feels_like}°C`\n"
                f"▪️ **Humidity:** `{humidity}%`\n"
                f"▪️ **Wind Speed:** `{wind_speed} m/s`\n"
                f"▪️ **Pressure:** `{pressure} hPa`\n"
                f"▪️ **Visibility:** `{visibility / 1000 if visibility else 'N/A'} km`"
            )
            await message.edit(response_text)
            logger.info(f"Weather info retrieved for '{city}'.")
            return
        elif json_data is not None and json_data.get('cod') == '404':
            await message.edit(f"`City '{city}' not found. Please check the spelling.`")
            logger.warning(f"City '{city}' not found for weather query.")
        else:
            await message.edit(f"`Failed to retrieve weather information for '{city}'.`")
            logger.error(f"Failed to retrieve weather for '{city}'. JSON data was: {json_data}")

# -------------------------------------------------------------------------
# Command: .whois - Detailed user information.
# -------------------------------------------------------------------------
@app.on_message(filters.me & filters.command("whois", prefixes=COMMAND_PREFIX))
async def whois_command_handler(client: Client, message: Message):
    """
    Handles the .whois command to retrieve detailed information about a user.
    Can be used by replying to a message, providing a user ID, or no arguments (for self).
    """
    logger.info(f"Command {COMMAND_PREFIX}whois executed by user {message.from_user.id}.")
    target_user_id = await get_target_user_id(message)
    
    if not target_user_id and message.from_user:
        target_user_id = message.from_user.id # If no target, get info about self
    
    if not target_user_id:
        await message.edit(f"`Please reply to a user, provide their ID, or a username.`")
        return

    await message.edit(f"`Gathering information for user ID {target_user_id}...`")
    try:
        user_info = await client.get_users(target_user_id)
        
        status_text = ""
        if user_info.status == "online":
            status_text = "Online 🟢"
        elif user_info.status == "offline":
            status_text = "Offline 🔴"
            if user_info.last_online_date:
                last_seen = datetime.fromtimestamp(user_info.last_online_date).strftime('%Y-%m-%d %H:%M:%S UTC')
                status_text += f" (Last seen: {last_seen})"
        elif user_info.status == "recently":
            status_text = "Recently Online 🟡"
        elif user_info.status == "long_ago":
            status_text = "Long time ago ⚪"
        else:
            status_text = "Unknown"

        # Try to get user bio (requires userbot to have chat access or user to be in common chat)
        bio = "N/A"
        try:
            full_user_chat = await client.get_chat(target_user_id)
            if full_user_chat and full_user_chat.bio:
                bio = full_user_chat.bio
        except Exception as bio_e:
            logger.debug(f"Could not fetch bio for {target_user_id}: {bio_e}")

        response_text = (
            f"**🔎 User Information:**\n"
            f"▪️ **First Name:** `{user_info.first_name}`\n"
            f"▪️ **Last Name:** `{user_info.last_name or 'N/A'}`\n"
            f"▪️ **Username:** `@{user_info.username or 'N/A'}`\n"
            f"▪️ **User ID:** `{user_info.id}`\n"
            f"▪️ **Status:** `{status_text}`\n"
            f"▪️ **Is Bot?**: `{'Yes' if user_info.is_bot else 'No'}`\n"
            f"▪️ **Is Verified?**: `{'Yes' if user_info.is_verified else 'No'}`\n"
            f"▪️ **Is Scam?**: `{'Yes' if user_info.is_scam else 'No'}`\n"
            f"▪️ **Is Restricted?**: `{'Yes' if user_info.is_restricted else 'No'}`\n"
            f"▪️ **Profile Link:** [Link](tg://user?id={user_info.id})\n"
            f"▪️ **Bio:** ```\n{bio}```"
        )
        
        await message.edit(response_text)
        logger.info(f"User info retrieved for {target_user_id}.")

    except PeerIdInvalid:
        await message.edit(f"`User with ID/Username '{target_user_id}' not found.`")
        logger.warning(f"User '{target_user_id}' not found for whois command.")
    except Exception as e:
        logger.error(f"Error in whois command: {e}", exc_info=True)
        await message.edit(f"Error retrieving user information: `{e}`")

# -------------------------------------------------------------------------
# Command: .ginfo - Comprehensive group information.
# -------------------------------------------------------------------------
@app.on_message(filters.me & filters.command("ginfo", prefixes=COMMAND_PREFIX))
async def ginfo_command_handler(client: Client, message: Message):
    """
    Handles the .ginfo command to retrieve comprehensive information about the current chat.
    Works for groups, supergroups, and channels.
    """
    logger.info(f"Command {COMMAND_PREFIX}ginfo executed by user {message.from_user.id}.")
    if not message.chat.type in ["group", "supergroup", "channel"]:
        await message.edit("`This command only works in groups or channels.`")
        return

    await message.edit("`Gathering group/channel information... ℹ️`")
    try:
        chat_info = await client.get_chat(message.chat.id)
        
        title = chat_info.title
        chat_id = chat_info.id
        username = chat_info.username or "N/A"
        members_count = await client.get_chat_members_count(chat_id)
        description = chat_info.description or "No description."
        
        chat_type_map = {
            "group": "Basic Group",
            "supergroup": "Supergroup",
            "channel": "Channel",
            "private": "Private Chat"
        }

        response_text = (
            f"**ℹ️ Group/Channel Information:**\n"
            f"▪️ **Title:** `{title}`\n"
            f"▪️ **Chat ID:** `{chat_id}`\n"
            f"▪️ **Username (Link):** `@{username}`\n"
            f"▪️ **Type:** `{chat_type_map.get(str(chat_info.type), 'Unknown')}`\n"
            f"▪️ **Members Count:** `{members_count}`\n"
            f"▪️ **Is Scam?**: `{'Yes' if chat_info.is_scam else 'No'}`\n"
            f"▪️ **Is Restricted?**: `{'Yes' if chat_info.is_restricted else 'No'}`\n"
            f"▪️ **Description:** ```\n{description}```\n"
        )
        
        await message.edit(response_text)
        logger.info(f"Group info retrieved for chat {chat_id}.")

    except Exception as e:
        logger.error(f"Error in ginfo command: {e}", exc_info=True)
        await message.edit(f"Error retrieving group information: `{e}`")

# -------------------------------------------------------------------------
# Command: .covid - COVID-19 statistics (Simulated/Placeholder)
# -------------------------------------------------------------------------
@app.on_message(filters.me & filters.command("covid", prefixes=COMMAND_PREFIX))
async def covid_command_handler(client: Client, message: Message):
    """
    Handles the .covid command to display COVID-19 statistics for a country.
    This is a simulated command; a real implementation would require a COVID-19 API.
    """
    logger.info(f"Command {COMMAND_PREFIX}covid executed by user {message.from_user.id}.")
    country = await extract_arg(message)
    if not country:
        await message.edit(f"`Please provide a country name for COVID-19 stats! (Example: {COMMAND_PREFIX}covid Iran)`")
        return

    await message.edit(f"`Fetching COVID-19 stats for '{country}'... 🦠 (Simulated)`")
    try:
        # Placeholder for actual API call, e.g., worldometers.info via scraping or a dedicated API.
        # Example: https://disease.sh/v3/covid-19/countries/Iran
        async with aiohttp.ClientSession() as session:
            api_url = f"https://disease.sh/v3/covid-19/countries/{requests.utils.quote(country)}"
            json_data = await http_get_json(api_url, session)

            if json_data and json_data.get('country'):
                country_name = json_data['country']
                cases = json_data.get('cases', 0)
                today_cases = json_data.get('todayCases', 0)
                deaths = json_data.get('deaths', 0)
                today_deaths = json_data.get('todayDeaths', 0)
                recovered = json_data.get('recovered', 0)
                active = json_data.get('active', 0)
                critical = json_data.get('critical', 0)

                response_text = (
                    f"**🦠 COVID-19 Statistics for {country_name}:**\n"
                    f"▪️ **Total Cases:** `{cases:,}`\n"
                    f"▪️ **New Cases Today:** `{today_cases:,}`\n"
                    f"▪️ **Total Deaths:** `{deaths:,}`\n"
                    f"▪️ **New Deaths Today:** `{today_deaths:,}`\n"
                    f"▪️ **Total Recovered:** `{recovered:,}`\n"
                    f"▪️ **Active Cases:** `{active:,}`\n"
                    f"▪️ **Critical Cases:** `{critical:,}`\n"
                    f"*(Data might not be real-time due to API limitations or simulation.)*"
                )
                await message.edit(response_text)
                logger.info(f"COVID-19 stats retrieved for '{country}'.")
                return
            else:
                await message.edit(f"`Could not find COVID-19 statistics for '{country}'. Please check country name.`")
                logger.warning(f"COVID-19 API failed for '{country}'.")
    except Exception as e:
        logger.error(f"Error in covid command: {e}", exc_info=True)
        await message.edit(f"Error fetching COVID-19 stats: `{e}`")

# -------------------------------------------------------------------------
# Command: .time - World time converter.
# -------------------------------------------------------------------------
@app.on_message(filters.me & filters.command("time", prefixes=COMMAND_PREFIX))
async def time_command_handler(client: Client, message: Message):
    """
    Handles the .time command to display the current time in a specified city or timezone.
    Uses an external API (e.g., worldtimeapi.org).
    """
    logger.info(f"Command {COMMAND_PREFIX}time executed by user {message.from_user.id}.")
    location = await extract_arg(message)
    if not location:
        await message.edit(f"`Please provide a city or timezone for time! (Example: {COMMAND_PREFIX}time London or {COMMAND_PREFIX}time Europe/London)`")
        return
    
    await message.edit(f"`Fetching time for '{location}'... ⏳`")
    async with aiohttp.ClientSession() as session:
        # WorldTimeAPI supports /area/location (e.g., /Europe/London)
        # or /timezone (e.g., /Asia/Tehran)
        # We try to guess the format, or use a general search.
        
        # Simple attempt with common format or direct
        api_url = f"http://worldtimeapi.org/api/timezone/{requests.utils.quote(location)}"
        json_data = await http_get_json(api_url, session)

        if json_data:
            current_datetime_str = json_data.get('datetime')
            timezone = json_data.get('timezone')
            
            if current_datetime_str and timezone:
                current_time = datetime.fromisoformat(current_datetime_str.replace('Z', '+00:00')).strftime('%Y-%m-%d %H:%M:%S')
                response_text = (
                    f"**⏰ Current Time in {timezone}:**\n"
                    f"▪️ **Date & Time:** `{current_time}`"
                )
                await message.edit(response_text)
                logger.info(f"Time retrieved for '{location}'.")
                return
        
        await message.edit(f"`Could not find time for '{location}'. Please check city/timezone spelling (e.g., Europe/London).`")
        logger.warning(f"Time API failed for '{location}'.")
    except Exception as e:
        logger.error(f"Error in time command: {e}", exc_info=True)
        await message.edit(f"Error fetching time: `{e}`")

# -------------------------------------------------------------------------
# Command: .shorten - URL shortener (Simulated/Placeholder)
# -------------------------------------------------------------------------
@app.on_message(filters.me & filters.command("shorten", prefixes=COMMAND_PREFIX))
async def shorten_command_handler(client: Client, message: Message):
    """
    Handles the .shorten command to shorten a URL using a public shortening service.
    This is a simulated command; a real implementation would use a service like tinyurl.com's API.
    """
    logger.info(f"Command {COMMAND_PREFIX}shorten executed by user {message.from_user.id}.")
    url_to_shorten = await extract_arg(message)
    if not url_to_shorten:
        await message.edit(f"`Please provide a URL to shorten! (Example: {COMMAND_PREFIX}shorten https://very-long-link.com/path/to/resource)`")
        return
    
    # Basic URL validation (optional, but good practice)
    if not (url_to_shorten.startswith("http://") or url_to_shorten.startswith("https://")):
        url_to_shorten = "http://" + url_to_shorten

    await message.edit(f"`Shortening URL: {url_to_shorten}... (Simulated)`")
    try:
        # Actual API call example (e.g., TinyURL API - note: many free ones are rate-limited or require keys)
        # async with aiohttp.ClientSession() as session:
        #     api_url = f"http://tinyurl.com/api-create.php?url={requests.utils.quote(url_to_shorten)}"
        #     async with session.get(api_url) as response:
        #         if response.status == 200:
        #             shortened_url = await response.text()
        #             await message.edit(f"**🔗 Shortened URL:** `{shortened_url}`")
        #             logger.info(f"URL shortened: {url_to_shorten} -> {shortened_url}.")
        #             return

        # Simulated response
        # Create a "fake" short URL for demonstration
        fake_short_url = f"https://shrt.bot/{random.randint(10000, 99999)}" 
        response_text = (
            f"**🔗 Shortened URL (Simulated):**\n"
            f"Original: `{url_to_shorten}`\n"
            f"Shortened: `{fake_short_url}`\n"
            f"*(For real shortening, integrate with TinyURL/Bitly API.)*"
        )
        await message.edit(response_text)
        logger.info(f"Simulated URL shortening for '{url_to_shorten}'.")

    except Exception as e:
        logger.error(f"Error in shorten command (simulated): {e}", exc_info=True)
        await message.edit(f"Error shortening URL: `{e}`")

# -------------------------------------------------------------------------
# Command: .hash - Text hashing.
# -------------------------------------------------------------------------
import hashlib

@app.on_message(filters.me & filters.command("hash", prefixes=COMMAND_PREFIX))
async def hash_command_handler(client: Client, message: Message):
    """
    Handles the .hash command to generate MD5 and SHA256 hashes of input text.
    """
    logger.info(f"Command {COMMAND_PREFIX}hash executed by user {message.from_user.id}.")
    text = await extract_arg(message)
    if not text and message.reply_to_message and message.reply_to_message.text:
        text = message.reply_to_message.text
    elif not text:
        await message.edit(f"`Please provide text to hash or reply to a message.`")
        return

    await message.edit("`Calculating hashes... 🔒`")
    try:
        text_bytes = text.encode('utf-8')
        md5_hash = hashlib.md5(text_bytes).hexdigest()
        sha256_hash = hashlib.sha256(text_bytes).hexdigest()
        
        response_text = (
            f"**🔒 Hashes for your text:**\n"
            f"▪️ **MD5:** ```\n{md5_hash}```\n"
            f"▪️ **SHA256:** ```\n{sha256_hash}```"
        )
        await message.edit(response_text)
        logger.info(f"Hashes generated for text: '{text[:50]}...'.")
    except Exception as e:
        logger.error(f"Error in hash command: {e}", exc_info=True)
        await message.edit(f"Error generating hashes: `{e}`")

# -------------------------------------------------------------------------
# Command: .remind - Reminder system (persistent).
# -------------------------------------------------------------------------
async def parse_time_duration(duration_str: str) -> Optional[timedelta]:
    """Parses a string like '1h30m' or '2d' into a timedelta object."""
    duration_str = duration_str.lower()
    total_seconds = 0
    
    # Regex to find numbers followed by d, h, m, s
    pattern = re.compile(r'(\d+)([dhms])')
    matches = pattern.findall(duration_str)

    if not matches:
        return None

    for value_str, unit in matches:
        value = int(value_str)
        if unit == 'd':
            total_seconds += value * 86400
        elif unit == 'h':
            total_seconds += value * 3600
        elif unit == 'm':
            total_seconds += value * 60
        elif unit == 's':
            total_seconds += value
    
    if total_seconds == 0:
        return None
    return timedelta(seconds=total_seconds)

@app.on_message(filters.me & filters.command("remind", prefixes=COMMAND_PREFIX))
async def remind_command_handler(client: Client, message: Message):
    """
    Handles the .remind command to set a persistent reminder.
    Usage: .remind <duration> <message> (e.g., 1h30m Take a break)
    """
    logger.info(f"Command {COMMAND_PREFIX}remind executed by user {message.from_user.id}.")
    args = message.command
    if len(args) < 3:
        await message.edit(f"`Usage: {COMMAND_PREFIX}remind [duration] [message]`\n"
                           f"`Example: {COMMAND_PREFIX}remind 1h30m Take a break (duration: s, m, h, d)`")
        return

    duration_str = args
    reminder_text = " ".join(args[2:])

    duration = await parse_time_duration(duration_str)
    if not duration:
        await message.edit(f"`Invalid duration format. Use: 1h30m, 2d, 15m, 30s.`")
        return
    
    remind_time = datetime.utcnow() + duration

    try:
        with Session(engine) as session:
            new_reminder = Reminder(
                user_id=message.from_user.id,
                chat_id=message.chat.id,
                message_id=message.id, # The command message itself
                remind_time=remind_time,
                text=reminder_text,
                is_active=True
            )
            session.add(new_reminder)
            session.commit()
            session.refresh(new_reminder)

        await message.edit(f"**Reminder set!** I will remind you in approximately `{format_time_difference(duration.total_seconds())}` about: `{reminder_text}`")
        logger.info(f"Reminder set for {message.from_user.id} in chat {message.chat.id}.")
    except Exception as e:
        logger.error(f"Error setting reminder: {e}", exc_info=True)
        await message.edit(f"Error setting reminder: `{e}`")

# -------------------------------------------------------------------------
# Commands: .note, .getnote, .delnote, .allnotes - Persistent notes system.
# -------------------------------------------------------------------------
@app.on_message(filters.me & filters.command("note", prefixes=COMMAND_PREFIX))
async def set_note_command_handler(client: Client, message: Message):
    """
    Handles the .note command to save a persistent note.
    Usage: .note <note_name> <note_content>
    """
    logger.info(f"Command {COMMAND_PREFIX}note executed by user {message.from_user.id}.")
    args = message.command
    if len(args) < 3:
        await message.edit(f"`Usage: {COMMAND_PREFIX}note [name] [content]`")
        return

    note_name = args.lower()
    note_content = " ".join(args[2:])

    try:
        with Session(engine) as session:
            existing_note = session.exec(
                select(Note).where(Note.user_id == message.from_user.id, Note.name == note_name)
            ).first()

            if existing_note:
                existing_note.content = note_content
                session.add(existing_note)
                response = f"**Note '{note_name}' updated!**"
                logger.info(f"Note '{note_name}' updated for user {message.from_user.id}.")
            else:
                new_note = Note(
                    user_id=message.from_user.id,
                    chat_id=message.chat.id, # Store chat ID for context
                    name=note_name,
                    content=note_content
                )
                session.add(new_note)
                response = f"**Note '{note_name}' saved!**"
                logger.info(f"Note '{note_name}' saved for user {message.from_user.id}.")
            
            session.commit()
            await message.edit(response)
    except Exception as e:
        logger.error(f"Error saving/updating note: {e}", exc_info=True)
        await message.edit(f"Error saving/updating note: `{e}`")

@app.on_message(filters.me & filters.command("getnote", prefixes=COMMAND_PREFIX))
async def get_note_command_handler(client: Client, message: Message):
    """
    Handles the .getnote command to retrieve a saved note.
    Usage: .getnote <note_name>
    """
    logger.info(f"Command {COMMAND_PREFIX}getnote executed by user {message.from_user.id}.")
    args = message.command
    if len(args) < 2:
        await message.edit(f"`Usage: {COMMAND_PREFIX}getnote [name]`")
        return

    note_name = args.lower()

    try:
        with Session(engine) as session:
            note = session.exec(
                select(Note).where(Note.user_id == message.from_user.id, Note.name == note_name)
            ).first()

            if note:
                await message.edit(f"**📝 Note '{note_name}':**\n```\n{note.content}```")
                logger.info(f"Note '{note_name}' retrieved for user {message.from_user.id}.")
            else:
                await message.edit(f"`Note '{note_name}' not found.`")
                logger.warning(f"Note '{note_name}' not found for user {message.from_user.id}.")
    except Exception as e:
        logger.error(f"Error retrieving note: {e}", exc_info=True)
        await message.edit(f"Error retrieving note: `{e}`")

@app.on_message(filters.me & filters.command("delnote", prefixes=COMMAND_PREFIX))
async def delete_note_command_handler(client: Client, message: Message):
    """
    Handles the .delnote command to delete a saved note.
    Usage: .delnote <note_name>
    """
    logger.info(f"Command {COMMAND_PREFIX}delnote executed by user {message.from_user.id}.")
    args = message.command
    if len(args) < 2:
        await message.edit(f"`Usage: {COMMAND_PREFIX}delnote [name]`")
        return

    note_name = args.lower()

    try:
        with Session(engine) as session:
            note = session.exec(
                select(Note).where(Note.user_id == message.from_user.id, Note.name == note_name)
            ).first()

            if note:
                session.delete(note)
                session.commit()
                await message.edit(f"**Note '{note_name}' deleted!**")
                logger.info(f"Note '{note_name}' deleted for user {message.from_user.id}.")
            else:
                await message.edit(f"`Note '{note_name}' not found.`")
                logger.warning(f"Note '{note_name}' not found for user {message.from_user.id}.")
    except Exception as e:
        logger.error(f"Error deleting note: {e}", exc_info=True)
        await message.edit(f"Error deleting note: `{e}`")

@app.on_message(filters.me & filters.command("allnotes", prefixes=COMMAND_PREFIX))
async def list_all_notes_command_handler(client: Client, message: Message):
    """
    Handles the .allnotes command to list all saved notes for the userbot owner.
    """
    logger.info(f"Command {COMMAND_PREFIX}allnotes executed by user {message.from_user.id}.")
    try:
        with Session(engine) as session:
            notes = session.exec(
                select(Note).where(Note.user_id == message.from_user.id)
            ).all()

            if notes:
                response_text = "**📝 Your Saved Notes:**\n\n"
                for i, note in enumerate(notes):
                    response_text += f"`{i+1}. {note.name}`\n"
                await message.edit(response_text)
                logger.info(f"Listed {len(notes)} notes for user {message.from_user.id}.")
            else:
                await message.edit("`You don't have any saved notes.`")
                logger.info(f"No notes found for user {message.from_user.id}.")
    except Exception as e:
        logger.error(f"Error listing notes: {e}", exc_info=True)
        await message.edit(f"Error listing notes: `{e}`")

# =========================================================================
# SECTION 9: IMPLEMENTATION OF ADMIN TOOLS (GROUP MANAGEMENT)
# These commands require the userbot to have appropriate admin rights in the chat.
# =========================================================================

# -------------------------------------------------------------------------
# Command: .ban - Bans a user.
# -------------------------------------------------------------------------
@app.on_message(filters.me & filters.command("ban", prefixes=COMMAND_PREFIX))
@require_admin_rights(['can_restrict_members']) # For banning
async def ban_command_handler(client: Client, message: Message):
    """
    Handles the .ban command to ban a user from a group.
    Supports optional duration and reason.
    """
    logger.info(f"Command {COMMAND_PREFIX}ban executed by user {message.from_user.id}.")
    target_user_id = await get_target_user_id(message)
    if not target_user_id:
        await message.edit("`Please reply to a user, or provide their ID/username.`")
        return

    if target_user_id == client.me.id:
        await message.edit("`I cannot ban myself!`")
        return
    
    # Extract duration and reason
    args = message.command
    duration_str = None
    reason_parts = []
    
    # After .ban or .ban <user_id>
    if len(args) > 2: # Check if there are more args after command and target
        # Try to parse the second argument as duration
        possible_duration_str = args
        if re.fullmatch(r'\d+[smhd]', possible_duration_str.lower()):
            duration_str = possible_duration_str
            reason_parts = args[3:]
        else:
            reason_parts = args[2:]
    
    reason = " ".join(reason_parts) if reason_parts else "No reason provided."

    until_date: Optional[datetime] = None
    if duration_str:
        duration = await parse_time_duration(duration_str)
        if duration:
            until_date = datetime.utcnow() + duration
        else:
            await message.edit("`Invalid duration format. Banning permanently.`")
            # Continue with permanent ban
    
    try:
        await client.ban_chat_member(
            chat_id=message.chat.id,
            user_id=target_user_id,
            until_date=until_date # None for permanent ban
        )
        time_info = f" for `{format_time_difference(duration.total_seconds())}`" if duration else " permanently"
        response_text = (
            f"**User with ID `{target_user_id}` banned{time_info}.**\n"
            f"**Reason:** `{reason}`"
        )
        await message.edit(response_text)
        logger.info(f"User {target_user_id} banned in chat {message.chat.id}. Duration: {time_info}, Reason: {reason}.")
    except UserAdminInvalid:
        await message.edit("`I cannot ban this user (they might be an admin or I lack sufficient privileges).`")
        logger.warning(f"Cannot ban {target_user_id} in {message.chat.id} due to insufficient privileges or target is admin.")
    except BadRequest as e:
        await message.edit(f"`Bad request error during ban: {e}`")
        logger.error(f"BadRequest in ban command: {e}", exc_info=True)
    except Exception as e:
        logger.error(f"Error in ban command: {e}", exc_info=True)
        await message.edit(f"Error banning user: `{e}`")

# -------------------------------------------------------------------------
# Command: .unban - Unbans a user.
# -------------------------------------------------------------------------
@app.on_message(filters.me & filters.command("unban", prefixes=COMMAND_PREFIX))
@require_admin_rights(['can_restrict_members'])
async def unban_command_handler(client: Client, message: Message):
    """
    Handles the .unban command to unban a user from a group.
    """
    logger.info(f"Command {COMMAND_PREFIX}unban executed by user {message.from_user.id}.")
    target_user_id = await get_target_user_id(message)
    if not target_user_id:
        await message.edit("`Please reply to a user, or provide their ID/username.`")
        return

    try:
        await client.unban_chat_member(chat_id=message.chat.id, user_id=target_user_id)
        response_text = f"**User with ID `{target_user_id}` successfully unbanned.**"
        await message.edit(response_text)
        logger.info(f"User {target_user_id} unbanned in chat {message.chat.id}.")
    except UserAdminInvalid:
        await message.edit("`I cannot unban this user (they might be an admin).`")
        logger.warning(f"Cannot unban {target_user_id} in {message.chat.id} due to insufficient privileges or target is admin.")
    except BadRequest as e:
        await message.edit(f"`Bad request error during unban: {e}`")
        logger.error(f"BadRequest in unban command: {e}", exc_info=True)
    except Exception as e:
        logger.error(f"Error in unban command: {e}", exc_info=True)
        await message.edit(f"Error unbanning user: `{e}`")

# -------------------------------------------------------------------------
# Command: .kick - Kicks a user.
# -------------------------------------------------------------------------
@app.on_message(filters.me & filters.command("kick", prefixes=COMMAND_PREFIX))
@require_admin_rights(['can_restrict_members'])
async def kick_command_handler(client: Client, message: Message):
    """
    Handles the .kick command to kick a user from a group.
    Note: Kicking is essentially a temporary ban, allowing the user to rejoin later.
    """
    logger.info(f"Command {COMMAND_PREFIX}kick executed by user {message.from_user.id}.")
    target_user_id = await get_target_user_id(message)
    if not target_user_id:
        await message.edit("`Please reply to a user, or provide their ID/username.`")
        return

    if target_user_id == client.me.id:
        await message.edit("`I cannot kick myself!`")
        return

    try:
        # Kicking means banning for a very short period (1 second) and then unbanning immediately.
        # This allows the user to rejoin.
        await client.ban_chat_member(chat_id=message.chat.id, user_id=target_user_id, until_date=datetime.utcnow() + timedelta(seconds=1))
        await message.edit(f"**User with ID `{target_user_id}` successfully kicked.**")
        logger.info(f"User {target_user_id} kicked from chat {message.chat.id}.")
    except UserAdminInvalid:
        await message.edit("`I cannot kick this user (they might be an admin or I lack sufficient privileges).`")
        logger.warning(f"Cannot kick {target_user_id} in {message.chat.id} due to insufficient privileges or target is admin.")
    except BadRequest as e:
        await message.edit(f"`Bad request error during kick: {e}`")
        logger.error(f"BadRequest in kick command: {e}", exc_info=True)
    except Exception as e:
        logger.error(f"Error in kick command: {e}", exc_info=True)
        await message.edit(f"Error kicking user: `{e}`")

# -------------------------------------------------------------------------
# Command: .mute - Mutes a user.
# -------------------------------------------------------------------------
@app.on_message(filters.me & filters.command("mute", prefixes=COMMAND_PREFIX))
@require_admin_rights(['can_restrict_members'])
async def mute_command_handler(client: Client, message: Message):
    """
    Handles the .mute command to restrict a user's permissions in a group.
    Supports optional duration and reason.
    """
    logger.info(f"Command {COMMAND_PREFIX}mute executed by user {message.from_user.id}.")
    target_user_id = await get_target_user_id(message)
    if not target_user_id:
        await message.edit("`Please reply to a user, or provide their ID/username.`")
        return

    if target_user_id == client.me.id:
        await message.edit("`I cannot mute myself!`")
        return

    # Extract duration and reason
    args = message.command
    duration_str = None
    reason_parts = []
    
    if len(args) > 2: # Check if there are more args after command and target
        possible_duration_str = args
        if re.fullmatch(r'\d+[smhd]', possible_duration_str.lower()):
            duration_str = possible_duration_str
            reason_parts = args[3:]
        else:
            reason_parts = args[2:]
    
    reason = " ".join(reason_parts) if reason_parts else "No reason provided."

    until_date: Optional[datetime] = None
    if duration_str:
        duration = await parse_time_duration(duration_str)
        if duration:
            until_date = datetime.utcnow() + duration
        else:
            await message.edit("`Invalid duration format. Muting permanently.`")
            # Continue with permanent mute
    
    try:
        # Restrict all common permissions
        await client.restrict_chat_member(
            chat_id=message.chat.id,
            user_id=target_user_id,
            permissions=ChatPermissions(can_send_messages=False), # Only restrict sending messages
            until_date=until_date
        )
        time_info = f" for `{format_time_difference(duration.total_seconds())}`" if duration else " permanently"
        response_text = (
            f"**User with ID `{target_user_id}` muted{time_info}.**\n"
            f"**Reason:** `{reason}`"
        )
        await message.edit(response_text)
        logger.info(f"User {target_user_id} muted in chat {message.chat.id}. Duration: {time_info}, Reason: {reason}.")
    except UserAdminInvalid:
        await message.edit("`I cannot mute this user (they might be an admin or I lack sufficient privileges).`")
        logger.warning(f"Cannot mute {target_user_id} in {message.chat.id} due to insufficient privileges or target is admin.")
    except BadRequest as e:
        await message.edit(f"`Bad request error during mute: {e}`")
        logger.error(f"BadRequest in mute command: {e}", exc_info=True)
    except Exception as e:
        logger.error(f"Error in mute command: {e}", exc_info=True)
        await message.edit(f"Error muting user: `{e}`")

# -------------------------------------------------------------------------
# Command: .unmute - Unmutes a user.
# -------------------------------------------------------------------------
@app.on_message(filters.me & filters.command("unmute", prefixes=COMMAND_PREFIX))
@require_admin_rights(['can_restrict_members'])
async def unmute_command_handler(client: Client, message: Message):
    """
    Handles the .unmute command to restore a user's permissions in a group.
    """
    logger.info(f"Command {COMMAND_PREFIX}unmute executed by user {message.from_user.id}.")
    target_user_id = await get_target_user_id(message)
    if not target_user_id:
        await message.edit("`Please reply to a user, or provide their ID/username.`")
        return

    try:
        # Grant all common permissions back
        await client.restrict_chat_member(
            chat_id=message.chat.id,
            user_id=target_user_id,
            permissions=ChatPermissions(
                can_send_messages=True,
                can_send_media_messages=True,
                can_send_stickers=True,
                can_send_animations=True,
                can_send_games=True,
                can_use_inline_bots=True,
                can_add_web_page_previews=True,
                can_send_polls=True,
                # Admin-specific permissions should remain False unless explicitly promoted
                can_change_info=False,
                can_invite_users=True,
                can_pin_messages=False
            )
        )
        await message.edit(f"**User with ID `{target_user_id}` successfully unmuted.**")
        logger.info(f"User {target_user_id} unmuted in chat {message.chat.id}.")
    except UserAdminInvalid:
        await message.edit("`I cannot unmute this user (they might be an admin or I lack sufficient privileges).`")
        logger.warning(f"Cannot unmute {target_user_id} in {message.chat.id} due to insufficient privileges or target is admin.")
    except BadRequest as e:
        await message.edit(f"`Bad request error during unmute: {e}`")
        logger.error(f"BadRequest in unmute command: {e}", exc_info=True)
    except Exception as e:
        logger.error(f"Error in unmute command: {e}", exc_info=True)
        await message.edit(f"Error unmuting user: `{e}`")

# -------------------------------------------------------------------------
# Command: .promote - Promotes a user to admin.
# -------------------------------------------------------------------------
@app.on_message(filters.me & filters.command("promote", prefixes=COMMAND_PREFIX))
@require_admin_rights(['can_promote_members'])
async def promote_command_handler(client: Client, message: Message):
    """
    Handles the .promote command to promote a user to administrator with specific permissions.
    Usage: .promote [reply/user_id] [permission1] [permission2] ...
    Example: .promote @user can_delete_messages can_pin_messages
    """
    logger.info(f"Command {COMMAND_PREFIX}promote executed by user {message.from_user.id}.")
    target_user_id = await get_target_user_id(message)
    if not target_user_id:
        await message.edit("`Please reply to a user, or provide their ID/username.`")
        return

    if target_user_id == client.me.id:
        await message.edit("`I cannot promote myself (or demote myself)!`")
        return

    permissions_args = message.command[2:] # Get arguments after command and user ID

    # Default permissions (no specific rights)
    can_change_info = False
    can_post_messages = False
    can_edit_messages = False
    can_delete_messages = False
    can_restrict_members = False
    can_invite_users = False
    can_pin_messages = False
    can_manage_video_chats = False
    is_anonymous = False

    # Parse permissions from arguments
    # 'admin' keyword grants all basic admin rights (excluding 'is_anonymous')
    if 'admin' in permissions_args:
        can_change_info = True
        can_post_messages = True
        can_edit_messages = True
        can_delete_messages = True
        can_restrict_members = True
        can_invite_users = True
        can_pin_messages = True
        can_manage_video_chats = True
        # is_anonymous = False (default, usually set explicitly)
        permissions_text = "full admin rights (excluding anonymous)"
    else:
        for perm in permissions_args:
            if perm == "can_change_info": can_change_info = True
            elif perm == "can_post_messages": can_post_messages = True
            elif perm == "can_edit_messages": can_edit_messages = True
            elif perm == "can_delete_messages": can_delete_messages = True
            elif perm == "can_restrict_members": can_restrict_members = True
            elif perm == "can_invite_users": can_invite_users = True
            elif perm == "can_pin_messages": can_pin_messages = True
            elif perm == "can_manage_video_chats": can_manage_video_chats = True
            elif perm == "is_anonymous": is_anonymous = True
        permissions_text = ", ".join(permissions_args) or "no specific rights (regular member)"

    try:
        await client.promote_chat_member(
            chat_id=message.chat.id,
            user_id=target_user_id,
            can_change_info=can_change_info,
            can_post_messages=can_post_messages,
            can_edit_messages=can_edit_messages,
            can_delete_messages=can_delete_messages,
            can_restrict_members=can_restrict_members,
            can_invite_users=can_invite_users,
            can_pin_messages=can_pin_messages,
            can_manage_video_chats=can_manage_video_chats,
            is_anonymous=is_anonymous
        )
        await message.edit(f"**User with ID `{target_user_id}` promoted with {permissions_text}.**")
        logger.info(f"User {target_user_id} promoted in chat {message.chat.id} with rights: {permissions_text}.")
    except UserAdminInvalid:
        await message.edit("`I cannot promote this user (they might already be an admin with higher rights, or I lack sufficient privileges).`")
        logger.warning(f"Cannot promote {target_user_id} in {message.chat.id} due to insufficient privileges or target admin status.")
    except BadRequest as e:
        await message.edit(f"`Bad request error during promote: {e}`")
        logger.error(f"BadRequest in promote command: {e}", exc_info=True)
    except Exception as e:
        logger.error(f"Error in promote command: {e}", exc_info=True)
        await message.edit(f"Error promoting user: `{e}`")

# -------------------------------------------------------------------------
# Command: .demote - Demotes an admin.
# -------------------------------------------------------------------------
@app.on_message(filters.me & filters.command("demote", prefixes=COMMAND_PREFIX))
@require_admin_rights(['can_promote_members'])
async def demote_command_handler(client: Client, message: Message):
    """
    Handles the .demote command to demote an administrator back to a regular member.
    """
    logger.info(f"Command {COMMAND_PREFIX}demote executed by user {message.from_user.id}.")
    target_user_id = await get_target_user_id(message)
    if not target_user_id:
        await message.edit("`Please reply to a user, or provide their ID/username.`")
        return

    if target_user_id == client.me.id:
        await message.edit("`I cannot demote myself!`")
        return

    try:
        # Promote with all permissions set to False
        await client.promote_chat_member(
            chat_id=message.chat.id,
            user_id=target_user_id,
            can_change_info=False,
            can_post_messages=False,
            can_edit_messages=False,
            can_delete_messages=False,
            can_restrict_members=False,
            can_invite_users=False,
            can_pin_messages=False,
            can_manage_video_chats=False,
            is_anonymous=False
        )
        await message.edit(f"**User with ID `{target_user_id}` successfully demoted.**")
        logger.info(f"User {target_user_id} demoted in chat {message.chat.id}.")
    except UserAdminInvalid:
        await message.edit("`I cannot demote this user (they might be an owner or have higher rights than me).`")
        logger.warning(f"Cannot demote {target_user_id} in {message.chat.id} due to insufficient privileges or target is owner.")
    except BadRequest as e:
        await message.edit(f"`Bad request error during demote: {e}`")
        logger.error(f"BadRequest in demote command: {e}", exc_info=True)
    except Exception as e:
        logger.error(f"Error in demote command: {e}", exc_info=True)
        await message.edit(f"Error demoting user: `{e}`")

# -------------------------------------------------------------------------
# Command: .pin - Pins a message.
# -------------------------------------------------------------------------
@app.on_message(filters.me & filters.command("pin", prefixes=COMMAND_PREFIX))
@require_admin_rights(['can_pin_messages'])
async def pin_command_handler(client: Client, message: Message):
    """
    Handles the .pin command to pin a replied message in a group.
    """
    logger.info(f"Command {COMMAND_PREFIX}pin executed by user {message.from_user.id}.")
    if not message.reply_to_message:
        await message.edit("`Please reply to a message to pin it.`")
        return

    try:
        await client.pin_chat_message(
            chat_id=message.chat.id,
            message_id=message.reply_to_message.id,
            disable_notification=False # Set to True to pin silently
        )
        await message.edit(f"**Message `{message.reply_to_message.id}` successfully pinned.**")
        logger.info(f"Message {message.reply_to_message.id} pinned in chat {message.chat.id}.")
    except BadRequest as e:
        await message.edit(f"`Bad request error during pin: {e}`")
        logger.error(f"BadRequest in pin command: {e}", exc_info=True)
    except Exception as e:
        logger.error(f"Error in pin command: {e}", exc_info=True)
        await message.edit(f"Error pinning message: `{e}`")

# -------------------------------------------------------------------------
# Command: .unpin - Unpins a message or all messages.
# -------------------------------------------------------------------------
@app.on_message(filters.me & filters.command("unpin", prefixes=COMMAND_PREFIX))
@require_admin_rights(['can_pin_messages'])
async def unpin_command_handler(client: Client, message: Message):
    """
    Handles the .unpin command to unpin a replied message or all pinned messages.
    Usage: .unpin (replied to a message) or .unpin all
    """
    logger.info(f"Command {COMMAND_PREFIX}unpin executed by user {message.from_user.id}.")
    arg = await extract_arg(message)

    try:
        if message.reply_to_message:
            await client.unpin_chat_message(
                chat_id=message.chat.id,
                message_id=message.reply_to_message.id
            )
            await message.edit(f"**Message `{message.reply_to_message.id}` successfully unpinned.**")
            logger.info(f"Message {message.reply_to_message.id} unpinned in chat {message.chat.id}.")
        elif arg and arg.lower() == "all":
            await client.unpin_all_chat_messages(chat_id=message.chat.id)
            await message.edit(f"**All pinned messages successfully unpinned.**")
            logger.info(f"All pinned messages unpinned in chat {message.chat.id}.")
        else:
            await message.edit("`Please reply to a message to unpin it, or use '.unpin all' to unpin all messages.`")
            return
    except MessageIdInvalid:
        await message.edit("`The replied message is not pinned.`")
        logger.warning(f"Tried to unpin non-pinned message {message.reply_to_message.id}.")
    except BadRequest as e:
        await message.edit(f"`Bad request error during unpin: {e}`")
        logger.error(f"BadRequest in unpin command: {e}", exc_info=True)
    except Exception as e:
        logger.error(f"Error in unpin command: {e}", exc_info=True)
        await message.edit(f"Error unpinning message(s): `{e}`")

# -------------------------------------------------------------------------
# Command: .del - Deletes a replied message.
# -------------------------------------------------------------------------
@app.on_message(filters.me & filters.command("del", prefixes=COMMAND_PREFIX))
@require_admin_rights(['can_delete_messages'])
async def del_command_handler(client: Client, message: Message):
    """
    Handles the .del command to delete a replied message (not the command itself).
    """
    logger.info(f"Command {COMMAND_PREFIX}del executed by user {message.from_user.id}.")
    if not message.reply_to_message:
        await message.edit("`Please reply to a message to delete it.`")
        return
    
    try:
        # Delete both the command message and the replied message
        await client.delete_messages(
            chat_id=message.chat.id,
            message_ids=[message.id, message.reply_to_message.id]
        )
        logger.info(f"Message {message.reply_to_message.id} deleted by user {message.from_user.id}.")
    except BadRequest as e:
        await message.edit(f"`Bad request error during deletion: {e}`")
        logger.error(f"BadRequest in del command: {e}", exc_info=True)
    except Exception as e:
        logger.error(f"Error in del command: {e}", exc_info=True)
        await message.edit(f"Error deleting message: `{e}`")

# -------------------------------------------------------------------------
# Command: .setgtitle - Sets group title.
# -------------------------------------------------------------------------
@app.on_message(filters.me & filters.command("setgtitle", prefixes=COMMAND_PREFIX))
@require_admin_rights(['can_change_info'])
async def setgtitle_command_handler(client: Client, message: Message):
    """
    Handles the .setgtitle command to change the group's title.
    """
    logger.info(f"Command {COMMAND_PREFIX}setgtitle executed by user {message.from_user.id}.")
    new_title = await extract_arg(message)
    if not new_title:
        await message.edit("`Please provide a new title for the group!`")
        return
    
    try:
        await client.set_chat_title(chat_id=message.chat.id, title=new_title)
        await message.edit(f"**Group title successfully changed to:** `{new_title}`")
        logger.info(f"Group title of {message.chat.id} changed to '{new_title}'.")
    except BadRequest as e:
        await message.edit(f"`Bad request error changing title: {e}`")
        logger.error(f"BadRequest in setgtitle command: {e}", exc_info=True)
    except Exception as e:
        logger.error(f"Error in setgtitle command: {e}", exc_info=True)
        await message.edit(f"Error setting group title: `{e}`")

# -------------------------------------------------------------------------
# Command: .setgdesc - Sets group description.
# -------------------------------------------------------------------------
@app.on_message(filters.me & filters.command("setgdesc", prefixes=COMMAND_PREFIX))
@require_admin_rights(['can_change_info'])
async def setgdesc_command_handler(client: Client, message: Message):
    """
    Handles the .setgdesc command to change the group's description.
    """
    logger.info(f"Command {COMMAND_PREFIX}setgdesc executed by user {message.from_user.id}.")
    new_description = await extract_arg(message)
    if new_description is None: # Allow empty string to clear description
        await message.edit("`Please provide a new description for the group, or use an empty string to clear it.`")
        return
    
    try:
        await client.set_chat_description(chat_id=message.chat.id, description=new_description)
        await message.edit(f"**Group description successfully changed to:** ```\n{new_description or 'Cleared'}```")
        logger.info(f"Group description of {message.chat.id} changed.")
    except BadRequest as e:
        await message.edit(f"`Bad request error changing description: {e}`")
        logger.error(f"BadRequest in setgdesc command: {e}", exc_info=True)
    except Exception as e:
        logger.error(f"Error in setgdesc command: {e}", exc_info=True)
        await message.edit(f"Error setting group description: `{e}`")

# -------------------------------------------------------------------------
# Commands: .warn, .unwarn, .warnings - Warning system (persistent).
# -------------------------------------------------------------------------
@app.on_message(filters.me & filters.command("warn", prefixes=COMMAND_PREFIX))
@require_admin_rights(['can_restrict_members'])
async def warn_command_handler(client: Client, message: Message):
    """
    Handles the .warn command to issue a warning to a user.
    Warnings are stored persistently in the database.
    """
    logger.info(f"Command {COMMAND_PREFIX}warn executed by user {message.from_user.id}.")
    target_user_id = await get_target_user_id(message)
    if not target_user_id:
        await message.edit("`Please reply to a user, or provide their ID/username.`")
        return

    if target_user_id == client.me.id:
        await message.edit("`I cannot warn myself!`")
        return

    reason = await extract_arg(message)
    if not reason:
        reason = "No reason specified."

    try:
        with Session(engine) as session:
            new_warning = Warning(
                user_id=target_user_id,
                chat_id=message.chat.id,
                admin_id=message.from_user.id,
                reason=reason
            )
            session.add(new_warning)
            session.commit()
            session.refresh(new_warning)

            # Count current warnings for the user
            user_warnings = session.exec(
                select(Warning).where(Warning.user_id == target_user_id, Warning.chat_id == message.chat.id)
            ).all()

            user_info = await client.get_users(target_user_id)
            user_mention = f"[{user_info.first_name}](tg://user?id={user_info.id})"

            await message.edit(
                f"**User {user_mention} warned!**\n"
                f"**Reason:** `{reason}`\n"
                f"**Total Warnings:** `{len(user_warnings)}`"
            )
            logger.info(f"User {target_user_id} warned in chat {message.chat.id}. Total warnings: {len(user_warnings)}.")
    except Exception as e:
        logger.error(f"Error in warn command: {e}", exc_info=True)
        await message.edit(f"Error warning user: `{e}`")

@app.on_message(filters.me & filters.command("unwarn", prefixes=COMMAND_PREFIX))
@require_admin_rights(['can_restrict_members'])
async def unwarn_command_handler(client: Client, message: Message):
    """
    Handles the .unwarn command to remove the most recent warning from a user.
    """
    logger.info(f"Command {COMMAND_PREFIX}unwarn executed by user {message.from_user.id}.")
    target_user_id = await get_target_user_id(message)
    if not target_user_id:
        await message.edit("`Please reply to a user, or provide their ID/username.`")
        return

    try:
        with Session(engine) as session:
            # Get the most recent warning for the user in this chat
            warnings = session.exec(
                select(Warning).where(Warning.user_id == target_user_id, Warning.chat_id == message.chat.id)
                .order_by(Warning.timestamp.desc())
            ).all()

            if warnings:
                oldest_warning = warnings[-1] # Remove the first (oldest) warning
                session.delete(oldest_warning)
                session.commit()
                
                user_info = await client.get_users(target_user_id)
                user_mention = f"[{user_info.first_name}](tg://user?id={user_info.id})"
                
                remaining_warnings = len(warnings) - 1
                await message.edit(
                    f"**One warning removed for {user_mention}!**\n"
                    f"**Remaining Warnings:** `{remaining_warnings}`"
                )
                logger.info(f"One warning removed for user {target_user_id} in chat {message.chat.id}. Remaining: {remaining_warnings}.")
            else:
                await message.edit(f"`User has no warnings in this chat.`")
                logger.warning(f"No warnings found for user {target_user_id} to unwarn.")
    except Exception as e:
        logger.error(f"Error in unwarn command: {e}", exc_info=True)
        await message.edit(f"Error removing warning: `{e}`")

@app.on_message(filters.me & filters.command("warnings", prefixes=COMMAND_PREFIX))
async def list_warnings_command_handler(client: Client, message: Message):
    """
    Handles the .warnings command to list all warnings for a user.
    """
    logger.info(f"Command {COMMAND_PREFIX}warnings executed by user {message.from_user.id}.")
    target_user_id = await get_target_user_id(message)
    if not target_user_id:
        await message.edit("`Please reply to a user, or provide their ID/username.`")
        return

    try:
        with Session(engine) as session:
            warnings = session.exec(
                select(Warning).where(Warning.user_id == target_user_id, Warning.chat_id == message.chat.id)
                .order_by(Warning.timestamp.asc()) # Show oldest first
            ).all()

            user_info = await client.get_users(target_user_id)
            user_mention = f"[{user_info.first_name}](tg://user?id={user_info.id})"

            if warnings:
                response_text = f"**⚠️ Warnings for {user_mention} ({len(warnings)} total):**\n\n"
                for i, warn in enumerate(warnings):
                    admin_info = await client.get_users(warn.admin_id)
                    admin_mention = f"[{admin_info.first_name}](tg://user?id={admin_info.id})"
                    response_text += (
                        f"**{i+1}.** `Date: {warn.timestamp.strftime('%Y-%m-%d %H:%M')}`\n"
                        f"   `Reason: {warn.reason}`\n"
                        f"   `Admin: {admin_mention}`\n\n"
                    )
                
                # Check message length before sending
                if len(response_text) > 4096:
                    # If too long, send as a document
                    with io.BytesIO(response_text.encode('utf-8')) as f:
                        f.name = "warnings.txt"
                        await client.send_document(
                            chat_id=message.chat.id,
                            document=f,
                            caption=f"**Warnings for {user_mention}**"
                        )
                    await message.delete()
                else:
                    await message.edit(response_text)
                logger.info(f"Listed {len(warnings)} warnings for user {target_user_id}.")
            else:
                await message.edit(f"**{user_mention} has no warnings in this chat.**")
                logger.info(f"No warnings found for user {target_user_id}.")
    except Exception as e:
        logger.error(f"Error listing warnings: {e}", exc_info=True)
        await message.edit(f"Error listing warnings: `{e}`")

# -------------------------------------------------------------------------
# Commands: .gban, .ungban - Global Ban/Unban (EXTREMELY DANGEROUS)
# These commands affect the userbot's behavior across ALL joined groups.
# They are generally NOT recommended for public userbots and should be used
# with extreme caution by the userbot owner only.
# -------------------------------------------------------------------------
@app.on_message(filters.me & filters.command("gban", prefixes=COMMAND_PREFIX))
async def gban_command_handler(client: Client, message: Message):
    """
    Handles the .gban command to globally ban a user from all groups the userbot is in.
    EXTREMELY DANGEROUS - USE WITH CAUTION. This does not use Telegram's API for global ban,
    but rather a local blacklist that the userbot enforces.
    """
    logger.critical(f"Command {COMMAND_PREFIX}gban executed by user {message.from_user.id}. (EXTREMELY DANGEROUS!)")
    target_user_id = await get_target_user_id(message)
    if not target_user_id:
        await message.edit("`Please reply to a user, or provide their ID/username to Gban.`")
        return

    if target_user_id == client.me.id:
        await message.edit("`I cannot gban myself!`")
        return

    reason = await extract_arg(message)
    if not reason or reason == str(target_user_id):
        reason = "Globally banned by userbot owner."

    try:
        with Session(engine) as session:
            # Store gban status in UserSetting
            existing_gban = session.exec(
                select(UserSetting).where(UserSetting.user_id == target_user_id, UserSetting.key == "gban_status")
            ).first()

            if existing_gban:
                existing_gban.value = reason
                session.add(existing_gban)
                response = f"**User `{target_user_id}`'s global ban reason updated to:** `{reason}`"
            else:
                new_gban = UserSetting(user_id=target_user_id, key="gban_status", value=reason)
                session.add(new_gban)
                response = f"**User `{target_user_id}` globally banned.**\n**Reason:** `{reason}`"
            
            session.commit()
            await message.edit(response + "\n`Userbot will attempt to restrict/kick this user in all joined chats.`")
            logger.critical(f"User {target_user_id} globally banned by userbot. Reason: {reason}.")
            
            # Optionally, iterate through all chats and ban/kick (this could take a very long time for many chats)
            await message.reply("`Attempting to kick/ban user from all accessible chats...`")
            async for dialog in client.get_dialogs():
                if dialog.chat.type in ["group", "supergroup", "channel"] and dialog.chat.id != message.chat.id:
                    try:
                        # Check if userbot has ban rights in this chat
                        if await check_userbot_rights_in_chat(dialog.chat.id, ['can_restrict_members']):
                            await client.ban_chat_member(dialog.chat.id, target_user_id)
                            logger.info(f"GBan: Kicked {target_user_id} from {dialog.chat.id}.")
                        else:
                            logger.warning(f"GBan: No restrict rights in {dialog.chat.id} for {target_user_id}.")
                    except Exception as e:
                        logger.error(f"GBan: Error processing {target_user_id} in {dialog.chat.id}: {e}")
                await asyncio.sleep(0.1) # Small delay to avoid flood waits
            await message.reply("`Global ban processing complete (or attempted) across all chats.`")

    except Exception as e:
        logger.error(f"Error in gban command: {e}", exc_info=True)
        await message.edit(f"Error globally banning user: `{e}`")

@app.on_message(filters.me & filters.command("ungban", prefixes=COMMAND_PREFIX))
async def ungban_command_handler(client: Client, message: Message):
    """
    Handles the .ungban command to remove a global ban for a user.
    """
    logger.critical(f"Command {COMMAND_PREFIX}ungban executed by user {message.from_user.id}.")
    target_user_id = await get_target_user_id(message)
    if not target_user_id:
        await message.edit("`Please reply to a user, or provide their ID/username to Ungban.`")
        return

    try:
        with Session(engine) as session:
            gban_setting = session.exec(
                select(UserSetting).where(UserSetting.user_id == target_user_id, UserSetting.key == "gban_status")
            ).first()

            if gban_setting:
                session.delete(gban_setting)
                session.commit()
                await message.edit(f"**User `{target_user_id}` globally unbanned.**")
                logger.critical(f"User {target_user_id} globally unbanned by userbot.")
                # Optionally, iterate through chats and unban (can take long)
                await message.reply("`Attempting to unban user from all accessible chats...`")
                async for dialog in client.get_dialogs():
                    if dialog.chat.type in ["group", "supergroup", "channel"] and dialog.chat.id != message.chat.id:
                        try:
                            if await check_userbot_rights_in_chat(dialog.chat.id, ['can_restrict_members']):
                                await client.unban_chat_member(dialog.chat.id, target_user_id)
                                logger.info(f"UnGBan: Unbanned {target_user_id} from {dialog.chat.id}.")
                            else:
                                logger.warning(f"UnGBan: No restrict rights in {dialog.chat.id} for {target_user_id}.")
                        except Exception as e:
                            logger.error(f"UnGBan: Error processing {target_user_id} in {dialog.chat.id}: {e}")
                    await asyncio.sleep(0.1)
                await message.reply("`Global unban processing complete (or attempted) across all chats.`")
            else:
                await message.edit(f"`User `{target_user_id}` is not globally banned.`")
                logger.warning(f"User {target_user_id} not found in global ban list.")
    except Exception as e:
        logger.error(f"Error in ungban command: {e}", exc_info=True)
        await message.edit(f"Error globally unbanning user: `{e}`")

# -------------------------------------------------------------------------
# Event handler to enforce global ban for new members
# This should be placed at the end of event handlers.
# -------------------------------------------------------------------------
@app.on_message(filters.new_chat_members)
async def enforce_gban_on_new_members(client: Client, message: Message):
    """
    Automatically checks if new chat members are globally banned and acts accordingly.
    """
    for new_member in message.new_chat_members:
        if new_member.id == client.me.id: # Ignore self joining
            continue

        with Session(engine) as session:
            gban_setting = session.exec(
                select(UserSetting).where(User_Setting.user_id == new_member.id, UserSetting.key == "gban_status")
            ).first()

            if gban_setting:
                reason = gban_setting.value
                try:
                    if await check_userbot_rights_in_chat(message.chat.id, ['can_restrict_members']):
                        await client.ban_chat_member(message.chat.id, new_member.id)
                        await client.send_message(
                            chat_id=message.chat.id,
                            text=f"**User {new_member.mention} (ID: `{new_member.id}`) was globally banned by userbot owner. Kicked!**\n**Reason:** `{reason}`"
                        )
                        logger.info(f"GBan enforced: Kicked {new_member.id} from {message.chat.id}.")
                    else:
                        logger.warning(f"GBan: No restrict rights in {message.chat.id} to kick {new_member.id}.")
                except Exception as e:
                    logger.error(f"Error enforcing gban for {new_member.id} in {message.chat.id}: {e}")

# -------------------------------------------------------------------------
# Commands: .setwelcome, .delwelcome - Customizable welcome messages.
# -------------------------------------------------------------------------
@app.on_message(filters.me & filters.command("setwelcome", prefixes=COMMAND_PREFIX))
@require_admin_rights(['can_restrict_members']) # Often, bots with welcome messages also have restrict rights
async def set_welcome_message_handler(client: Client, message: Message):
    """
    Handles the .setwelcome command to set a custom welcome message for a group.
    Supports basic markdown.
    """
    logger.info(f"Command {COMMAND_PREFIX}setwelcome executed by user {message.from_user.id}.")
    if not message.chat.type in ["group", "supergroup"]:
        await message.edit("`This command only works in groups.`")
        return

    welcome_text = await extract_arg(message)
    if not welcome_text:
        await message.edit(f"`Please provide a welcome message. Use {{user}} for new member's name.`")
        return

    try:
        with Session(engine) as session:
            chat_setting = session.exec(
                select(ChatSetting).where(ChatSetting.chat_id == message.chat.id, ChatSetting.key == "welcome_message")
            ).first()

            if chat_setting:
                chat_setting.value = welcome_text
                session.add(chat_setting)
                response = f"**Welcome message updated for this chat!**"
            else:
                new_setting = ChatSetting(chat_id=message.chat.id, key="welcome_message", value=welcome_text)
                session.add(new_setting)
                response = f"**Welcome message set for this chat!**"
            
            session.commit()
            await message.edit(response)
            logger.info(f"Welcome message set/updated in chat {message.chat.id}.")
    except Exception as e:
        logger.error(f"Error setting welcome message: {e}", exc_info=True)
        await message.edit(f"Error setting welcome message: `{e}`")

@app.on_message(filters.me & filters.command("delwelcome", prefixes=COMMAND_PREFIX))
@require_admin_rights(['can_restrict_members'])
async def del_welcome_message_handler(client: Client, message: Message):
    """
    Handles the .delwelcome command to delete the custom welcome message for a group.
    """
    logger.info(f"Command {COMMAND_PREFIX}delwelcome executed by user {message.from_user.id}.")
    if not message.chat.type in ["group", "supergroup"]:
        await message.edit("`This command only works in groups.`")
        return

    try:
        with Session(engine) as session:
            chat_setting = session.exec(
                select(ChatSetting).where(ChatSetting.chat_id == message.chat.id, ChatSetting.key == "welcome_message")
            ).first()

            if chat_setting:
                session.delete(chat_setting)
                session.commit()
                await message.edit(f"**Welcome message deleted for this chat!**")
                logger.info(f"Welcome message deleted in chat {message.chat.id}.")
            else:
                await message.edit(f"`No welcome message found for this chat.`")
                logger.warning(f"No welcome message to delete in chat {message.chat.id}.")
    except Exception as e:
        logger.error(f"Error deleting welcome message: {e}", exc_info=True)
        await message.edit(f"Error deleting welcome message: `{e}`")

# Event handler for new chat members (to send welcome message)
@app.on_message(filters.new_chat_members & filters.group)
async def welcome_new_member_event_handler(client: Client, message: Message):
    """
    Listens for new chat members and sends a custom welcome message if configured.
    """
    for new_member in message.new_chat_members:
        if new_member.id == client.me.id: # Ignore self joining
            continue
        
        with Session(engine) as session:
            chat_setting = session.exec(
                select(ChatSetting).where(ChatSetting.chat_id == message.chat.id, ChatSetting.key == "welcome_message")
            ).first()

            if chat_setting and chat_setting.value:
                welcome_text = chat_setting.value
                # Replace placeholders
                welcome_text = welcome_text.replace("{user}", new_member.mention)
                welcome_text = welcome_text.replace("{chat}", message.chat.title)
                
                try:
                    await client.send_message(
                        chat_id=message.chat.id,
                        text=welcome_text,
                        reply_to_message_id=message.id
                    )
                    logger.info(f"Sent welcome message to {new_member.id} in {message.chat.id}.")
                except Exception as e:
                    logger.error(f"Error sending welcome message to {new_member.id}: {e}", exc_info=True)

# -------------------------------------------------------------------------
# Commands: .antilink, .antiflood - Basic group protections.
# -------------------------------------------------------------------------
@app.on_message(filters.me & filters.command("antilink", prefixes=COMMAND_PREFIX))
@require_admin_rights(['can_delete_messages', 'can_restrict_members'])
async def antilink_command_handler(client: Client, message: Message):
    """
    Handles the .antilink command to toggle anti-link protection in a group.
    When enabled, deletes messages containing common URLs.
    """
    logger.info(f"Command {COMMAND_PREFIX}antilink executed by user {message.from_user.id}.")
    if not message.chat.type in ["group", "supergroup"]:
        await message.edit("`This command only works in groups.`")
        return

    arg = await extract_arg(message)
    if arg not in ["on", "off"]:
        await message.edit(f"`Usage: {COMMAND_PREFIX}antilink [on/off]`")
        return

    status = (arg == "on")
    try:
        with Session(engine) as session:
            chat_setting = session.exec(
                select(ChatSetting).where(ChatSetting.chat_id == message.chat.id, ChatSetting.key == "antilink_status")
            ).first()

            if chat_setting:
                chat_setting.value = str(status)
                session.add(chat_setting)
            else:
                new_setting = ChatSetting(chat_id=message.chat.id, key="antilink_status", value=str(status))
                session.add(new_setting)
            
            session.commit()
            await message.edit(f"**Anti-link protection set to: `{arg.upper()}`**")
            logger.info(f"Anti-link set to {arg} in chat {message.chat.id}.")
    except Exception as e:
        logger.error(f"Error setting antilink: {e}", exc_info=True)
        await message.edit(f"Error setting anti-link: `{e}`")

# Event handler for anti-link (delete messages with URLs)
@app.on_message(filters.group & ~filters.me) # Only process messages from others in groups
async def antilink_message_listener(client: Client, message: Message):
    """
    Listens for messages in groups. If anti-link is enabled,
    it deletes messages containing common URLs.
    """
    # Don't delete messages from admins or if bot doesn't have delete rights
    if not await check_userbot_rights_in_chat(message.chat.id, ['can_delete_messages']):
        return
    
    with Session(engine) as session:
        antilink_setting = session.exec(
            select(ChatSetting).where(ChatSetting.chat_id == message.chat.id, ChatSetting.key == "antilink_status")
        ).first()
        
        if antilink_setting and antilink_setting.value == "True":
            if message.text or message.caption:
                text_content = message.text or message.caption
                # Simple regex for URL detection (can be more sophisticated)
                url_pattern = r'https?://(?:[-\w.]|(?:%[\da-fA-F]{2}))+'
                if re.search(url_pattern, text_content):
                    try:
                        await message.delete()
                        # Optional: Send a warning message
                        # await client.send_message(message.chat.id, f"Link detected and removed from {message.from_user.mention}.", reply_to_message_id=message.id)
                        logger.info(f"Anti-link: Deleted message with URL from {message.from_user.id} in {message.chat.id}.")
                    except Forbidden:
                        logger.warning(f"Anti-link: Bot could not delete message from {message.from_user.id} in {message.chat.id} (permissions lost?).")
                    except Exception as e:
                        logger.error(f"Anti-link: Error deleting message: {e}", exc_info=True)

# Placeholder for antiflood
@app.on_message(filters.me & filters.command("antiflood", prefixes=COMMAND_PREFIX))
@require_admin_rights(['can_delete_messages', 'can_restrict_members'])
async def antiflood_command_handler(client: Client, message: Message):
    """
    Handles the .antiflood command to toggle anti-flood protection in a group.
    (Placeholder - implementation requires tracking user message rates).
    """
    logger.info(f"Command {COMMAND_PREFIX}antiflood executed by user {message.from_user.id}.")
    if not message.chat.type in ["group", "supergroup"]:
        await message.edit("`This command only works in groups.`")
        return

    args = message.command
    if len(args) < 2 or args not in ["on", "off"]:
        await message.edit(f"`Usage: {COMMAND_PREFIX}antiflood [on/off] [threshold (optional, default 5 in 10s)]`")
        return

    status = (args == "on")
    threshold = 5 # default messages
    time_window = 10 # default seconds
    
    if len(args) > 2:
        try:
            threshold = int(args)
            if threshold <= 0: raise ValueError
        except ValueError:
            await message.edit("`Invalid threshold. Must be a positive integer.`")
            return

    try:
        with Session(engine) as session:
            chat_setting = session.exec(
                select(ChatSetting).where(ChatSetting.chat_id == message.chat.id, ChatSetting.key == "antiflood_status")
            ).first()
            threshold_setting = session.exec(
                select(ChatSetting).where(ChatSetting.chat_id == message.chat.id, ChatSetting.key == "antiflood_threshold")
            ).first()

            if chat_setting: chat_setting.value = str(status)
            else: session.add(ChatSetting(chat_id=message.chat.id, key="antiflood_status", value=str(status)))
            
            if threshold_setting: threshold_setting.value = str(threshold)
            else: session.add(ChatSetting(chat_id=message.chat.id, key="antiflood_threshold", value=str(threshold)))
            
            session.commit()
            await message.edit(f"**Anti-flood protection set to: `{args[1].upper()}` with threshold `{threshold}` messages in `{time_window}` seconds.**\n"
                               f"*(Actual implementation of anti-flood logic is pending.)*")
            logger.info(f"Anti-flood set to {args} with threshold {threshold} in chat {message.chat.id}.")
    except Exception as e:
        logger.error(f"Error setting antiflood: {e}", exc_info=True)
        await message.edit(f"Error setting anti-flood: `{e}`")


# =========================================================================
# SECTION 10: IMPLEMENTATION OF AUTOMATION & UTILITY COMMANDS
# Commands for automated tasks, file handling, and other general utilities.
# =========================================================================

# -------------------------------------------------------------------------
# Command: .dl - File downloader from URL.
# -------------------------------------------------------------------------
@app.on_message(filters.me & filters.command("dl", prefixes=COMMAND_PREFIX))
async def download_command_handler(client: Client, message: Message):
    """
    Handles the .dl command to download a file from a given URL and upload it to Telegram.
    """
    logger.info(f"Command {COMMAND_PREFIX}dl executed by user {message.from_user.id}.")
    url_to_download = await extract_arg(message)
    if not url_to_download:
        await message.edit(f"`Please provide a URL to download! (Example: {COMMAND_PREFIX}dl https://example.com/image.jpg)`")
        return

    await message.edit(f"`Downloading from '{url_to_download}'... 📥`")
    
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(url_to_download, allow_redirects=True, timeout=30) as response:
                if response.status == 200:
                    content_type = response.headers.get('Content-Type', 'application/octet-stream')
                    file_extension = ""
                    if 'image/' in content_type:
                        file_extension = "." + content_type.split('/')[-1]
                    elif 'video/' in content_type:
                        file_extension = "." + content_type.split('/')[-1]
                    elif 'text/' in content_type:
                        file_extension = ".txt"
                    
                    filename = os.path.basename(url_to_download.split('?'))
                    if not "." in filename and file_extension: # Add extension if missing
                        filename = f"download{file_extension}"
                    elif not "." in filename: # Fallback
                        filename = "download.bin"

                    # Ensure filename is not too long or invalid for file systems
                    filename = re.sub(r'[\\/*?:"<>|]', '', filename)[:100]

                    temp_file = io.BytesIO(await response.read())
                    temp_file.name = filename # Pyrogram needs this for send_document

                    if 'image/' in content_type:
                        await client.send_photo(
                            chat_id=message.chat.id,
                            photo=temp_file,
                            caption=f"`Downloaded from:` {url_to_download}"
                        )
                    elif 'video/' in content_type:
                        await client.send_video(
                            chat_id=message.chat.id,
                            video=temp_file,
                            caption=f"`Downloaded from:` {url_to_download}"
                        )
                    else:
                        await client.send_document(
                            chat_id=message.chat.id,
                            document=temp_file,
                            caption=f"`Downloaded from:` {url_to_download}"
                        )
                    await message.delete()
                    logger.info(f"File downloaded from {url_to_download} and sent.")
                else:
                    await message.edit(f"`Failed to download. Status: {response.status}`")
                    logger.warning(f"Download failed for {url_to_download} with status {response.status}.")
    except aiohttp.ClientError as e:
        logger.error(f"HTTP Client error during download: {e}", exc_info=True)
        await message.edit(f"`Download failed: HTTP client error. {e}`")
    except asyncio.TimeoutError:
        logger.error(f"Download timeout for {url_to_download}.", exc_info=True)
        await message.edit(f"`Download timed out for: {url_to_download}`")
    except Exception as e:
        logger.error(f"Error in dl command: {e}", exc_info=True)
        await message.edit(f"Error downloading file: `{e}`")

# -------------------------------------------------------------------------
# Command: .up - File uploader to Telegram.
# -------------------------------------------------------------------------
@app.on_message(filters.me & filters.command("up", prefixes=COMMAND_PREFIX))
async def upload_command_handler(client: Client, message: Message):
    """
    Handles the .up command to upload a local file to Telegram.
    Usage: .up <file_path>
    """
    logger.info(f"Command {COMMAND_PREFIX}up executed by user {message.from_user.id}.")
    file_path = await extract_arg(message)
    if not file_path:
        await message.edit(f"`Please provide a local file path to upload! (Example: {COMMAND_PREFIX}up /tmp/myfile.txt)`")
        return
    
    if not os.path.exists(file_path):
        await message.edit(f"`File not found at path: {file_path}`")
        logger.warning(f"File not found for upload: {file_path}")
        return

    await message.edit(f"`Uploading '{os.path.basename(file_path)}'... ⬆️`")
    try:
        # Determine media type (simple guess)
        mime_type, _ = mimetypes.guess_type(file_path)
        is_photo = mime_type and mime_type.startswith('image/')
        is_video = mime_type and mime_type.startswith('video/')

        # Pyrogram automatically handles the file stream
        if is_photo:
            await client.send_photo(
                chat_id=message.chat.id,
                photo=file_path,
                caption=f"`Uploaded file:` `{os.path.basename(file_path)}`"
            )
        elif is_video:
            await client.send_video(
                chat_id=message.chat.id,
                video=file_path,
                caption=f"`Uploaded file:` `{os.path.basename(file_path)}`"
            )
        else:
            await client.send_document(
                chat_id=message.chat.id,
                document=file_path,
                caption=f"`Uploaded file:` `{os.path.basename(file_path)}`"
            )
        await message.delete()
        logger.info(f"File '{file_path}' uploaded and sent.")
    except Exception as e:
        logger.error(f"Error in up command: {e}", exc_info=True)
        await message.edit(f"Error uploading file: `{e}`")

# -------------------------------------------------------------------------
# Commands: .autobio, .autoname - Automatic account details setting.
# -------------------------------------------------------------------------
@app.on_message(filters.me & filters.command("autobio", prefixes=COMMAND_PREFIX))
async def autobio_command_handler(client: Client, message: Message):
    """
    Handles the .autobio command to set the userbot's biography.
    """
    logger.info(f"Command {COMMAND_PREFIX}autobio executed by user {message.from_user.id}.")
    new_bio = await extract_arg(message)
    if new_bio is None: # Allow empty string to clear bio
        await message.edit("`Please provide a new bio text, or use an empty string to clear it.`")
        return

    try:
        await client.update_profile(bio=new_bio)
        await message.edit(f"**Your biography successfully set to:** ```\n{new_bio or 'Cleared'}```")
        logger.info(f"Userbot bio set to: '{new_bio}'.")
    except Exception as e:
        logger.error(f"Error in autobio command: {e}", exc_info=True)
        await message.edit(f"Error setting bio: `{e}`")

@app.on_message(filters.me & filters.command("autoname", prefixes=COMMAND_PREFIX))
async def autoname_command_handler(client: Client, message: Message):
    """
    Handles the .autoname command to set the userbot's first and last name.
    Usage: .autoname [first_name] [last_name (optional)]
    """
    logger.info(f"Command {COMMAND_PREFIX}autoname executed by user {message.from_user.id}.")
    args = message.command
    if len(args) < 2:
        await message.edit("`Please provide a first name, and optionally a last name.`")
        return

    first_name = args
    last_name = " ".join(args[2:]) if len(args) > 2 else ""

    try:
        await client.update_profile(first_name=first_name, last_name=last_name)
        await message.edit(f"**Your name successfully set to:** `{first_name} {last_name}`")
        logger.info(f"Userbot name set to: '{first_name} {last_name}'.")
    except Exception as e:
        logger.error(f"Error in autoname command: {e}", exc_info=True)
        await message.edit(f"Error setting name: `{e}`")

# -------------------------------------------------------------------------
# Command: .scheduled - Scheduled message system (persistent).
# -------------------------------------------------------------------------
@app.on_message(filters.me & filters.command("scheduled", prefixes=COMMAND_PREFIX))
async def scheduled_message_command_handler(client: Client, message: Message):
    """
    Handles the .scheduled command to schedule a message to be sent at a future time.
    Usage: .scheduled <duration> <message> (e.g., 5m Hello there!)
    """
    logger.info(f"Command {COMMAND_PREFIX}scheduled executed by user {message.from_user.id}.")
    args = message.command
    if len(args) < 3:
        await message.edit(f"`Usage: {COMMAND_PREFIX}scheduled [duration] [message]`\n"
                           f"`Example: {COMMAND_PREFIX}scheduled 1h Hello World (duration: s, m, h, d)`")
        return

    duration_str = args
    message_text = " ".join(args[2:])

    duration = await parse_time_duration(duration_str)
    if not duration:
        await message.edit(f"`Invalid duration format. Use: 1h30m, 2d, 15m, 30s.`")
        return
    
    send_time = datetime.utcnow() + duration

    try:
        with Session(engine) as session:
            new_scheduled_msg = ScheduledMessage(
                user_id=message.from_user.id,
                chat_id=message.chat.id,
                send_time=send_time,
                message_text=message_text,
                is_sent=False
            )
            session.add(new_scheduled_msg)
            session.commit()
            session.refresh(new_scheduled_msg)

        await message.edit(f"**Message scheduled!** Will send in approximately `{format_time_difference(duration.total_seconds())}` to this chat: `{message_text[:100]}...`")
        logger.info(f"Message scheduled for chat {message.chat.id} by {message.from_user.id}.")
    except Exception as e:
        logger.error(f"Error scheduling message: {e}", exc_info=True)
        await message.edit(f"Error scheduling message: `{e}`")

# -------------------------------------------------------------------------
# Command: .count - Counts words/characters/lines.
# -------------------------------------------------------------------------
@app.on_message(filters.me & filters.command("count", prefixes=COMMAND_PREFIX))
async def count_command_handler(client: Client, message: Message):
    """
    Counts words, characters, and lines in the provided text or replied message.
    """
    logger.info(f"Command {COMMAND_PREFIX}count executed by user {message.from_user.id}.")
    text = await extract_arg(message)
    if not text and message.reply_to_message and message.reply_to_message.text:
        text = message.reply_to_message.text
    elif not text:
        await message.edit(f"`Please provide text to count or reply to a message.`")
        return

    word_count = len(text.split())
    char_count = len(text)
    line_count = text.count('\n') + 1

    response_text = (
        f"**📊 Text Statistics:**\n"
        f"▪️ **Words:** `{word_count}`\n"
        f"▪️ **Characters:** `{char_count}`\n"
        f"▪️ **Lines:** `{line_count}`"
    )
    await message.edit(response_text)
    logger.info(f"Counted text: words={word_count}, chars={char_count}, lines={line_count}.")

# -------------------------------------------------------------------------
# Command: .telegraph - Telegraph article creator (Simulated/Placeholder)
# -------------------------------------------------------------------------
@app.on_message(filters.me & filters.command("telegraph", prefixes=COMMAND_PREFIX))
async def telegraph_command_handler(client: Client, message: Message):
    """
    Handles the .telegraph command to create a Telegraph article.
    This is a simulated command; a real implementation would use the Telegraph API.
    """
    logger.info(f"Command {COMMAND_PREFIX}telegraph executed by user {message.from_user.id}.")
    args = message.command
    if len(args) < 2:
        await message.edit(f"`Usage: {COMMAND_PREFIX}telegraph [title] [author (optional)] [text/reply]`")
        return

    # Extract title, author, and content
    title = args
    author = ""
    content = ""

    # Check for author if it's the second arg and not the start of content
    if len(args) > 2 and not (args.startswith("http") or message.reply_to_message):
        author_candidate = args
        if len(args) > 3 or (not message.reply_to_message and len(args) == 3 and not await get_reply_text(message)):
            # If there's more after, or no reply and exactly 3 args, assume 2nd is author
            author = author_candidate
            content = " ".join(args[3:])
        else: # 2nd arg must be content
            content = " ".join(args[2:])
    elif len(args) > 2: # No explicit author, assume content starts from 2nd arg
        content = " ".join(args[2:])

    if not content and message.reply_to_message and message.reply_to_message.text:
        content = message.reply_to_message.text
    elif not content:
        await message.edit(f"`Please provide text for the Telegraph article or reply to a message.`")
        return
    
    if not author:
        author = client.me.first_name # Default author
    
    await message.edit(f"`Creating Telegraph article for '{title}'... (Simulated)`")
    try:
        # Real implementation using Telegraph API (pip install python-telegraph)
        # from telegraph import Telegraph
        # telegraph = Telegraph()
        # telegraph.create_account(short_name='YourBotName', author_name=author)
        # response = telegraph.create_page(
        #     title=title,
        #     html_content=f"<p>{content.replace('\n', '<br>')}</p>", # Basic HTML
        #     author_name=author
        # )
        # await message.edit(f"**📰 Telegraph Article:** [Link]({response['url']})")

        # Simulated response
        fake_telegraph_url = f"https://telegra.ph/{random.choice(['example', 'article', 'post'])}-{datetime.now().strftime('%m-%d-%H-%M-%S')}"
        response_text = (
            f"**📰 Telegraph Article (Simulated):**\n"
            f"**Title:** `{title}`\n"
            f"**Author:** `{author}`\n"
            f"**Content Snippet:** `{content[:100]}...`\n"
            f"**Link:** [Click here (simulated)]({fake_telegraph_url})\n"
            f"*(For real article creation, integrate with Telegraph API.)*"
        )
        await message.edit(response_text)
        logger.info(f"Simulated Telegraph article created for '{title}'.")
    except Exception as e:
        logger.error(f"Error in telegraph command (simulated): {e}", exc_info=True)
        await message.edit(f"Error creating Telegraph article: `{e}`")

# -------------------------------------------------------------------------
# Command: .imgedit - Basic image editor (Rotate, Resize) (Simulated/Placeholder)
# -------------------------------------------------------------------------
@app.on_message(filters.me & filters.command("imgedit", prefixes=COMMAND_PREFIX))
async def imgedit_command_handler(client: Client, message: Message):
    """
    Handles the .imgedit command for basic image manipulations (rotate, resize).
    This is a simulated command; a real implementation requires image processing with Pillow.
    """
    logger.info(f"Command {COMMAND_PREFIX}imgedit executed by user {message.from_user.id}.")
    if not message.reply_to_message or not message.reply_to_message.photo:
        await message.edit(f"`Please reply to a photo to edit it.`")
        return

    args = message.command
    if len(args) < 3 or args not in ["rotate", "resize"]:
        await message.edit(f"`Usage: {COMMAND_PREFIX}imgedit [rotate/resize] [value] (reply to photo)`\n"
                           f"`Example: {COMMAND_PREFIX}imgedit rotate 90`\n"
                           f"`Example: {COMMAND_PREFIX}imgedit resize 500` (for 500px width, maintains aspect ratio)")
        return
    
    action = args
    try:
        value = int(args)
    except ValueError:
        await message.edit(f"`Invalid value for {action}. Must be an integer.`")
        return

    await message.edit(f"`Processing image ({action})... 🖼️`")
    try:
        photo = message.reply_to_message.photo
        photo_path = await client.download_media(photo)
        
        with Image.open(photo_path) as img:
            edited_img = None
            if action == "rotate":
                edited_img = img.rotate(value, expand=True) # expand=True adjusts size for rotation
                status_msg = f"rotated by {value}°"
            elif action == "resize":
                original_width, original_height = img.size
                if value > original_width * 2 or value < 50: # Arbitrary limits
                    await message.edit("`Resize value out of reasonable range (50-2x original width).`")
                    os.remove(photo_path)
                    return
                
                # Resize keeping aspect ratio, 'value' is new width
                new_width = value
                new_height = int(original_height * (new_width / original_width))
                edited_img = img.resize((new_width, new_height), Image.LANCZOS)
                status_msg = f"resized to {new_width}px width"
            
            if edited_img:
                img_byte_arr = io.BytesIO()
                edited_img.save(img_byte_arr, format='PNG') # Save as PNG to preserve quality
                img_byte_arr.seek(0)
                
                await client.send_photo(
                    chat_id=message.chat.id,
                    photo=img_byte_arr,
                    caption=f"**Image {status_msg}.**"
                )
                await message.delete()
                logger.info(f"Image edited ({action}) and sent.")
            else:
                await message.edit(f"`Failed to perform image edit '{action}'.`")

        os.remove(photo_path)
    except Exception as e:
        logger.error(f"Error in imgedit command: {e}", exc_info=True)
        await message.edit(f"Error editing image: `{e}`")

# -------------------------------------------------------------------------
# Commands: .tofile, .tosticker, .tovoice - Media conversion utilities.
# -------------------------------------------------------------------------
@app.on_message(filters.me & filters.command("tofile", prefixes=COMMAND_PREFIX))
async def tofile_command_handler(client: Client, message: Message):
    """
    Converts a replied media message (photo, video, audio, sticker) into a document file.
    """
    logger.info(f"Command {COMMAND_PREFIX}tofile executed by user {message.from_user.id}.")
    if not message.reply_to_message or not message.reply_to_message.media:
        await message.edit("`Please reply to a media message to convert it to a file.`")
        return

    await message.edit("`Converting media to file... 💾`")
    try:
        # Download the media
        file_path = await client.download_media(message.reply_to_message)
        
        # Send as a document
        await client.send_document(
            chat_id=message.chat.id,
            document=file_path,
            caption=f"`Original media converted to file.`"
        )
        await message.delete()
        logger.info(f"Media converted to file: {file_path}.")
        os.remove(file_path) # Clean up downloaded file
    except Exception as e:
        logger.error(f"Error in tofile command: {e}", exc_info=True)
        await message.edit(f"Error converting media to file: `{e}`")

@app.on_message(filters.me & filters.command("tosticker", prefixes=COMMAND_PREFIX))
async def tosticker_command_handler(client: Client, message: Message):
    """
    Converts a replied photo to a static sticker. Similar to .sticker but specifically for photos.
    """
    logger.info(f"Command {COMMAND_PREFIX}tosticker executed by user {message.from_user.id}.")
    if not message.reply_to_message or not message.reply_to_message.photo:
        await message.edit(f"`Please reply to a photo message to convert it into a sticker.`")
        return
    
    # Delegate to the existing sticker command handler
    await sticker_command_handler(client, message)


@app.on_message(filters.me & filters.command("tovoice", prefixes=COMMAND_PREFIX))
async def tovoice_command_handler(client: Client, message: Message):
    """
    Converts a replied text message into a simulated voice message (Text-to-Speech).
    This is a placeholder/simulated command, requiring a TTS library or API.
    """
    logger.info(f"Command {COMMAND_PREFIX}tovoice executed by user {message.from_user.id}.")
    text_to_convert = await get_reply_text(message)
    if not text_to_convert:
        await message.edit("`Please reply to a text message to convert it to a voice message.`")
        return

    await message.edit(f"`Converting text to voice... 🎤 (Simulated)`")
    try:
        # Real implementation would involve:
        # 1. Using a TTS library (e.g., gTTS for Google TTS, pip install gTTS)
        # 2. Saving the generated audio to an in-memory BytesIO object (as .ogg for Telegram voice)
        # 3. Sending the BytesIO object as a voice message.
        
        # from gtts import gTTS
        # tts = gTTS(text=text_to_convert, lang='en')
        # audio_bytes = io.BytesIO()
        # tts.write_to_fp(audio_bytes)
        # audio_bytes.seek(0)
        # audio_bytes.name = "voice.ogg" # Telegram expects OGG for voice messages

        # await client.send_voice(
        #     chat_id=message.chat.id,
        #     voice=audio_bytes,
        #     caption=f"`Voice message from text.`"
        # )

        # For simulation: just confirm
        await message.edit(f"**Text converted to voice (simulated):** `{text_to_convert[:50]}...`\n"
                           f"*(For real conversion, a TTS library like gTTS is needed.)*")
        logger.info(f"Simulated TTS for text: '{text_to_convert[:50]}...'.")

    except Exception as e:
        logger.error(f"Error in tovoice command (simulated): {e}", exc_info=True)
        await message.edit(f"Error converting to voice: `{e}`")


# =========================================================================
# SECTION 11: HELP PANEL (.help) - DYNAMIC AND INTERACTIVE
# This section dynamically generates the help menu from the COMMANDS dictionary
# and handles inline keyboard navigation.
# =========================================================================

@app.on_message(filters.me & filters.command("help", prefixes=COMMAND_PREFIX))
async def help_command_handler(client: Client, message: Message):
    """
    Handles the .help command to display the main help menu with command categories.
    """
    logger.info(f"Command {COMMAND_PREFIX}help executed by user {message.from_user.id}.")
    await show_main_help_menu(message)

async def show_main_help_menu(message: Message):
    """Generates and displays the main help menu with categorized buttons."""
    help_text = "**👋 Your Self-Account Bot Help Panel 👋**\n\n"
    help_text += "*Click on a category button to view its commands.*\n"
    help_text += f"*All commands start with `{COMMAND_PREFIX}`.\n"
    
    buttons: List[List[InlineKeyboardButton]] = []
    row: List[InlineKeyboardButton] = []
    
    for category_name in COMMANDS.keys():
        row.append(InlineKeyboardButton(text=category_name, callback_data=f"help_cat_{category_name}"))
        if len(row) == 2: # 2 buttons per row for better layout
            buttons.append(row)
            row = []
    if row: # Add the last row if it's not full
        buttons.append(row)

    try:
        await message.edit(help_text, reply_markup=InlineKeyboardMarkup(buttons))
        logger.info("Main help panel displayed.")
    except Exception as e:
        logger.error(f"Error displaying main help panel: {e}", exc_info=True)
        await message.edit(f"Error displaying help panel: `{e}`")

@app.on_callback_query(filters.regex(r"^help_cat_"))
async def help_category_callback_handler(client: Client, callback_query: CallbackQuery):
    """
    Handles inline button callbacks for displaying commands within a specific category.
    """
    logger.info(f"Callback query '{callback_query.data}' received from user {callback_query.from_user.id}.")
    category_name = callback_query.data.replace("help_cat_", "")
    
    if category_name not in COMMANDS:
        await callback_query.answer("Category not found!", show_alert=True)
        logger.warning(f"Help category '{category_name}' not found.")
        return

    commands_in_category = COMMANDS[category_name]
    category_help_text = f"**📚 Commands in {category_name}:**\n\n"
    for cmd, desc in commands_in_category.items():
        category_help_text += f"• `{COMMAND_PREFIX}{cmd}`: {desc}\n"
    
    # Add a 'Back to Main Menu' button
    back_button = InlineKeyboardButton(text="⬅️ Back to Main Menu", callback_data="help_main_menu")
    
    try:
        await callback_query.edit_message_text(
            category_help_text,
            reply_markup=InlineKeyboardMarkup([[back_button]])
        )
        logger.info(f"Help category '{category_name}' displayed.")
        await callback_query.answer() # Acknowledge the callback query
    except Exception as e:
        logger.error(f"Error displaying help category '{category_name}': {e}", exc_info=True)
        await callback_query.answer(f"Error displaying: {e}", show_alert=True)

@app.on_callback_query(filters.regex(r"^help_main_menu"))
async def help_main_menu_callback_handler(client: Client, callback_query: CallbackQuery):
    """
    Handles inline button callbacks for returning to the main help menu.
    """
    logger.info(f"Callback query '{callback_query.data}' received from user {callback_query.from_user.id}.")
    # Re-display the main help menu
    help_text = "**👋 Your Self-Account Bot Help Panel 👋**\n\n"
    help_text += "*Click on a category button to view its commands.*\n"
    help_text += f"*All commands start with `{COMMAND_PREFIX}`.\n"
    
    buttons: List[List[InlineKeyboardButton]] = []
    row: List[InlineKeyboardButton] = []
    for category_name in COMMANDS.keys():
        row.append(InlineKeyboardButton(text=category_name, callback_data=f"help_cat_{category_name}"))
        if len(row) == 2:
            buttons.append(row)
            row = []
    if row:
        buttons.append(row)

    try:
        await callback_query.edit_message_text(help_text, reply_markup=InlineKeyboardMarkup(buttons))
        logger.info("Returned to main help panel.")
        await callback_query.answer()
    except Exception as e:
        logger.error(f"Error returning to main help menu: {e}", exc_info=True)
        await callback_query.answer(f"Error returning: {e}", show_alert=True)


# =========================================================================
# SECTION 12: EVENT HANDLERS AND BACKGROUND TASKS
# This section defines listeners for various Telegram events and
# tasks that run periodically in the background.
# =========================================================================

# Background task for checking and sending scheduled messages
async def scheduled_message_task():
    """
    Background task that periodically checks for due scheduled messages
    and sends them to the respective chats.
    """
    while True:
        await asyncio.sleep(30) # Check every 30 seconds
        logger.debug("Running scheduled message check.")
        with Session(engine) as session:
            try:
                # Find active scheduled messages that are due
                due_messages = session.exec(
                    select(ScheduledMessage).where(
                        ScheduledMessage.is_sent == False,
                        ScheduledMessage.send_time <= datetime.utcnow()
                    )
                ).all()

                for msg in due_messages:
                    try:
                        await app.send_message(
                            chat_id=msg.chat_id,
                            text=f"**⏰ Scheduled Reminder:**\n`{msg.message_text}`"
                        )
                        msg.is_sent = True # Mark as sent
                        session.add(msg)
                        logger.info(f"Sent scheduled message {msg.id} to chat {msg.chat_id}.")
                    except Forbidden:
                        logger.warning(f"Failed to send scheduled message {msg.id} to {msg.chat_id}: Bot forbidden (left chat?).")
                        msg.is_sent = True # Mark as sent to avoid repeated attempts
                        session.add(msg)
                    except Exception as e:
                        logger.error(f"Error sending scheduled message {msg.id} to {msg.chat_id}: {e}", exc_info=True)
                
                session.commit()
            except Exception as e:
                logger.error(f"Error in scheduled message background task: {e}", exc_info=True)

# Background task for checking and sending reminders
async def reminder_task():
    """
    Background task that periodically checks for due reminders
    and notifies the user.
    """
    while True:
        await asyncio.sleep(15) # Check every 15 seconds
        logger.debug("Running reminder check.")
        with Session(engine) as session:
            try:
                # Find active reminders that are due
                due_reminders = session.exec(
                    select(Reminder).where(
                        Reminder.is_active == True,
                        Reminder.remind_time <= datetime.utcnow()
                    )
                ).all()

                for rem in due_reminders:
                    try:
                        # Attempt to reply to original message, or send new message
                        if rem.message_id:
                            try:
                                await app.send_message(
                                    chat_id=rem.chat_id,
                                    text=f"**🔔 REMINDER:** `{rem.text}`",
                                    reply_to_message_id=rem.message_id
                                )
                            except MessageIdInvalid:
                                # Original message deleted, send as a new message
                                await app.send_message(
                                    chat_id=rem.chat_id,
                                    text=f"**🔔 REMINDER:** `{rem.text}`"
                                )
                        else:
                             await app.send_message(
                                chat_id=rem.chat_id,
                                text=f"**🔔 REMINDER:** `{rem.text}`"
                            )
                        
                        rem.is_active = False # Mark as inactive (sent)
                        session.add(rem)
                        logger.info(f"Sent reminder {rem.id} to user {rem.user_id} in chat {rem.chat_id}.")
                    except Forbidden:
                        logger.warning(f"Failed to send reminder {rem.id} to {rem.chat_id}: Bot forbidden (left chat?).")
                        rem.is_active = False # Mark as inactive
                        session.add(rem)
                    except Exception as e:
                        logger.error(f"Error sending reminder {rem.id} to {rem.user_id} in {rem.chat.id}: {e}", exc_info=True)
                
                session.commit()
            except Exception as e:
                logger.error(f"Error in reminder background task: {e}", exc_info=True)


# =========================================================================
# SECTION 13: BOT STARTUP AND SHUTDOWN MANAGEMENT
# Handles the lifecycle of the userbot, including starting background tasks.
# =========================================================================

async def main_runner():
    """
    Main function to start and manage the userbot.
    Initializes Pyrogram client, starts background tasks, and waits for termination.
    """
    logger.info("Userbot starting up...")
    try:
        await app.start()
        me = await app.get_me()
        logger.info(f"Userbot successfully started! As: {me.first_name} (@{me.username or me.id})")
        print(f"Userbot successfully started! As: {me.first_name} (@{me.username or me.id})")
        print(f"For commands, send '{COMMAND_PREFIX}help' in Telegram.")
        print("To stop the bot, press Ctrl+C.")

        # Start background tasks
        asyncio.create_task(scheduled_message_task())
        asyncio.create_task(reminder_task())
        logger.info("Background tasks started.")

        await idle() # Keep the bot running indefinitely
    except FloodWait as e:
        logger.critical(f"FloodWait during startup/runtime: {e.value} seconds. Please be patient.", exc_info=True)
        print(f"⚠️ FloodWait occurred. Please wait {e.value} seconds and try again.")
    except RPCError as e:
        logger.critical(f"RPC Error during startup: {e}", exc_info=True)
        print(f"❌ RPC Error during startup: {e}\nPlease check your API ID and API Hash.")
    except Exception as e:
        logger.critical(f"Unknown error during startup: {e}", exc_info=True)
        print(f"❌ Unknown error during startup: {e}")
    finally:
        logger.info("Userbot stopping...")
        if app.is_connected:
            await app.stop()
        logger.info("Userbot stopped.")
        print("Userbot stopped.")

if __name__ == "__main__":
    import mimetypes # Import here to avoid circular dependencies if used globally elsewhere
    asyncio.run(main_runner())
