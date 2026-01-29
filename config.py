import logging
import os
from dotenv import load_dotenv
from datetime import timedelta, timezone
from telethon import TelegramClient

# Load variables from .env file
load_dotenv()

# --- CONFIGURATION ---
# Now it reads from your .env file!
API_ID = int(os.getenv('API_ID', 0)) 
API_HASH = os.getenv('API_HASH', '')
BOT_TOKEN = os.getenv('BOT_TOKEN', '')
OWNER_ID = int(os.getenv('OWNER_ID', 0))

HEXA_ID = "HeXamonbot"
LOG_FILE = "safari_bot.log"
IST = timezone(timedelta(hours=5, minutes=30))

# --- DEFAULTS ---
DEFAULT_INTERVAL = 2.5  
DEFAULT_LIST = ["Mewtwo","Lugia","Ho-Oh","Celebi","Latias","Latios",
  "Kyogre","Groudon","Rayquaza","Jirachi","Deoxys","Dialga","Palkia",
  "Regigigas","Giratina","Cresselia",
  "Darkrai","Shaymin","Arceus",
  "Victini","Reshiram","Zekrom","Kyurem",
  "Keldeo","Genesect",
  "Xerneas","Yveltal","Zygarde","Hoopa","Cosmog","Cosmoem","Solgaleo",
  "Lunala","Necrozma","Magearna","Marshadow","Zeraora","Meltan","Melmetal",
  "Zacian","Zamazenta","Eternatus","Kubfu","Urshifu","Glastrier","Spectrier","Calyrex",
  "Enamorus"]

# --- GLOBAL STATE ---
user_clients = {}
user_configs = {}
user_tasks = {}

scheduler_settings = {
    'active': False,
    'start_time': "10:00 AM",
    'last_reset': None,
    'last_auto_start': None
}

# --- LOGGING ---
logging.basicConfig(
    format='%(asctime)s - %(levelname)s - %(message)s',
    level=logging.INFO,
    handlers=[
        logging.FileHandler(LOG_FILE),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger("SafariBot")

