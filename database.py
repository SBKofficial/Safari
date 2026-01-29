import sqlite3
import json
from config import logger, user_configs, DEFAULT_LIST, DEFAULT_INTERVAL

conn = sqlite3.connect('hexabot.db', check_same_thread=False)
cursor = conn.cursor()

def init_db():
    # Basic Table
    cursor.execute('''CREATE TABLE IF NOT EXISTS users 
                      (user_id INTEGER PRIMARY KEY, 
                       session TEXT, 
                       poke_list TEXT, 
                       ball TEXT,
                       total_matched INTEGER DEFAULT 0,
                       total_caught INTEGER DEFAULT 0,
                       total_fled INTEGER DEFAULT 0,
                       total_shiny INTEGER DEFAULT 0,
                       daily_matched INTEGER DEFAULT 0,   -- Added
                       daily_caught INTEGER DEFAULT 0,    -- Added
                       daily_fled INTEGER DEFAULT 0,      -- Added
                       daily_shiny INTEGER DEFAULT 0,     -- Added
                       start_time TEXT,
                       notification_status INTEGER DEFAULT 0,
                       group_id INTEGER DEFAULT 0,
                       interval REAL DEFAULT 2.5,
                       schedule_time TEXT DEFAULT NULL,
                       schedule_active INTEGER DEFAULT 0)''')
    
    cursor.execute('''CREATE TABLE IF NOT EXISTS settings 
                      (key TEXT PRIMARY KEY, value TEXT)''')
    
    # --- MIGRATIONS (Safe Updates) ---
    try: cursor.execute("ALTER TABLE users ADD COLUMN interval REAL DEFAULT 2.5")
    except: pass
    try: cursor.execute("ALTER TABLE users ADD COLUMN schedule_time TEXT DEFAULT NULL")
    except: pass
    try: cursor.execute("ALTER TABLE users ADD COLUMN schedule_active INTEGER DEFAULT 0")
    except: pass
    
    # Add Daily Columns if they don't exist
    for col in ['daily_matched', 'daily_caught', 'daily_fled', 'daily_shiny']:
        try: cursor.execute(f"ALTER TABLE users ADD COLUMN {col} INTEGER DEFAULT 0")
        except: pass
    
    conn.commit()

def load_users():
    cursor.execute("SELECT * FROM users")
    rows = cursor.fetchall()
    cols = [description[0] for description in cursor.description]
    
    loaded_data = []
    for row in rows:
        data = dict(zip(cols, row))
        uid = data['user_id']
        try: current_list = json.loads(data['poke_list'])
        except: current_list = DEFAULT_LIST
        
        user_configs[uid] = {
            'list': current_list, 
            'ball': data['ball'], 
            'hunting': False, 
            'mode': 'STOPPED',
            'interval': data.get('interval', DEFAULT_INTERVAL),
            'schedule_time': data.get('schedule_time'),
            'schedule_active': data.get('schedule_active', 0) == 1,
            'stats': {
                'total_caught': data['total_caught'], 
                'total_fled': data['total_fled'], 
                'total_matched': data['total_matched'],
                'total_shiny': data.get('total_shiny', 0),
                # Load Daily Stats
                'daily_caught': data.get('daily_caught', 0),
                'daily_fled': data.get('daily_fled', 0),
                'daily_matched': data.get('daily_matched', 0),
                'daily_shiny': data.get('daily_shiny', 0)
            }, 
            'notification_status': data['notification_status'], 
            'group_id': data['group_id']
        }
        loaded_data.append(data)
    return loaded_data

def update_schedule(user_id, time_str, active):
    active_int = 1 if active else 0
    cursor.execute("UPDATE users SET schedule_time = ?, schedule_active = ? WHERE user_id = ?", 
                   (time_str, active_int, user_id))
    conn.commit()
    if user_id in user_configs:
        user_configs[user_id]['schedule_time'] = time_str
        user_configs[user_id]['schedule_active'] = active

def update_db_interval(user_id, interval):
    cursor.execute("UPDATE users SET interval = ? WHERE user_id = ?", (interval, user_id))
    conn.commit()

def update_stat(user_id, column):
    """Updates BOTH Total and Daily stats."""
    valid_cols = ['matched', 'caught', 'fled', 'shiny']
    target_type = column.replace('total_', '')
    
    if target_type not in valid_cols: return

    # Update DB: Increment Total AND Daily
    daily_col = f"daily_{target_type}"
    cursor.execute(f"UPDATE users SET {column} = {column} + 1, {daily_col} = {daily_col} + 1 WHERE user_id = ?", (user_id,))
    conn.commit()
    
    # Update Memory
    if user_id in user_configs:
        user_configs[user_id]['stats'][column] += 1
        # Initialize daily stat in memory if missing
        if daily_col not in user_configs[user_id]['stats']:
            user_configs[user_id]['stats'][daily_col] = 0
        user_configs[user_id]['stats'][daily_col] += 1

def reset_daily_stats():
    """Resets only daily columns to 0."""
    logger.info("Reseting Daily Stats...")
    cursor.execute("UPDATE users SET daily_matched=0, daily_caught=0, daily_fled=0, daily_shiny=0")
    conn.commit()
    
    # Update Memory
    for uid in user_configs:
        user_configs[uid]['stats']['daily_matched'] = 0
        user_configs[uid]['stats']['daily_caught'] = 0
        user_configs[uid]['stats']['daily_fled'] = 0
        user_configs[uid]['stats']['daily_shiny'] = 0

init_db()

