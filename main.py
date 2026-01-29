import asyncio
import os
import io
import zipfile
import json
from datetime import datetime
from telethon import TelegramClient, events
from telethon.sessions import StringSession
from telethon.errors import SessionPasswordNeededError

from config import *
import database as db
from safari_client import run_userbot, auto_enter_loop

# Initialize Master Bot
master = TelegramClient('master_bot', API_ID, API_HASH).start(bot_token=BOT_TOKEN)

# --- NOTIFICATION CALLBACK ---
async def notify_user(user_id, message, file_path=None):
    """Callback passed to userbot to send alerts via Master Bot."""
    try:
        config = user_configs.get(user_id)
        if not config: return

        # DM User
        try:
            if file_path: await master.send_file(user_id, file_path, caption=message)
            else: await master.send_message(user_id, message)
        except: pass

        # Group Notification
        if config.get('notification_status') == 1 and config.get('group_id'):
            gid = config['group_id']
            try:
                if file_path: await master.send_file(gid, file_path, caption=message)
                else: await master.send_message(gid, message)
            except: pass
    except Exception as e:
        logger.error(f"Notify Error: {e}")

# ================= USER COMMANDS =================

@master.on(events.NewMessage(pattern='/safari'))
async def start_safari(event):
    uid = event.sender_id
    if uid not in user_configs: return await event.reply("Please /login first.")
    
    user_configs[uid]['hunting'] = True
    user_configs[uid]['mode'] = 'SAFARI_INIT'
    
    # Trigger auto-enter loop
    if uid in user_clients:
        asyncio.create_task(auto_enter_loop(user_clients[uid], uid))
        await event.reply(f"**Safari Started!**\nTimer: `{user_configs[uid].get('interval', DEFAULT_INTERVAL)}s`")
    else:
        await event.reply("(!) Client not connected. Try /login again.")

@master.on(events.NewMessage(pattern='/exit'))
async def stop_safari(event):
    uid = event.sender_id
    if uid in user_configs:
        user_configs[uid]['hunting'] = False
        user_configs[uid]['mode'] = 'STOPPED'
        await event.reply("Safari Stopped.")

@master.on(events.NewMessage(pattern=r'/timer (?P<val>\d+(\.\d+)?)'))
async def set_timer(event):
    uid = event.sender_id
    if uid not in user_configs: return await event.reply("Login first.")
    
    try:
        val = float(event.pattern_match.group('val'))
        if val < 1.0: return await event.reply("Minimum timer is 1.0s")
        
        user_configs[uid]['interval'] = val
        db.update_db_interval(uid, val)
        await event.reply(f"✅ **Timer Updated!**\nNew Interval: `{val} seconds`")
    except ValueError:
        await event.reply("Invalid number.")

@master.on(events.NewMessage(pattern=r'/schedule (.+)'))
async def set_schedule(event):
    """Sets the per-user auto-start time."""
    uid = event.sender_id
    if uid not in user_configs: return await event.reply("Login first.")
    
    input_str = event.pattern_match.group(1).strip()
    
    # Handle OFF
    if input_str.lower() == 'off':
        db.update_schedule(uid, None, False)
        return await event.reply("🔕 **Schedule Disabled.**")
        
    # Handle Time Set
    try:
        # Validate format HH:MM AM/PM
        dt = datetime.strptime(input_str.upper(), "%I:%M %p")
        time_fmt = dt.strftime("%I:%M %p") # Normalize format
        
        db.update_schedule(uid, time_fmt, True)
        
        await event.reply(f"⏰ **Schedule Set!**\n"
                          f"Bot will auto-start daily at: `{time_fmt}` (IST)\n"
                          f"To disable: `/schedule off`")
    except ValueError:
        await event.reply("(!) **Invalid Format.**\nUse `HH:MM AM` or `HH:MM PM`\nExample: `/schedule 10:30 AM`")

@master.on(events.NewMessage(pattern='/info'))
async def info(event):
    uid = event.sender_id
    if uid not in user_configs: return
    c = user_configs[uid]
    
    sched_info = f"{c.get('schedule_time')} [ON]" if c.get('schedule_active') else "OFF"
    
    msg = (f"**User Status**\n"
           f"State: {'🟢 Active' if c['hunting'] else '🔴 Stopped'}\n"
           f"Timer: `{c.get('interval', DEFAULT_INTERVAL)}s`\n"
           f"Schedule: `{sched_info}`\n"
           f"Matched: {c['stats']['total_matched']} | Shiny: {c['stats']['total_shiny']}")
    await event.reply(msg)

@master.on(events.NewMessage(pattern='/slogin'))
async def string_login(event):
    uid = event.sender_id
    text = event.text.split(' ', 1)
    
    if len(text) < 2:
        return await event.reply("Usage: `/slogin <session_string>`\n\n_Send this in DM only!_")
    
    session_str = text[1].strip()
    await event.delete() 
    
    msg = await event.reply("Validating session...")
    
    try:
        client = TelegramClient(StringSession(session_str), API_ID, API_HASH)
        await client.connect()
        
        if not await client.is_user_authorized():
            return await msg.edit("❌ **Invalid or Revoked Session.**")
            
        me = await client.get_me()
        await client.disconnect()
        
        cursor = db.conn.cursor()
        now = datetime.now().isoformat()
        cursor.execute("INSERT OR REPLACE INTO users (user_id, session, poke_list, ball, start_time, interval) VALUES (?, ?, ?, ?, ?, ?)", 
                       (uid, session_str, json.dumps(DEFAULT_LIST), "Safari Ball", now, DEFAULT_INTERVAL))
        db.conn.commit()
        
        user_configs[uid] = {
            'list': DEFAULT_LIST, 'ball': "Safari Ball", 
            'hunting': False, 'mode': 'STOPPED', 'interval': DEFAULT_INTERVAL,
            'stats': {'total_caught': 0, 'total_fled': 0, 'total_matched': 0, 'total_shiny': 0},
            'notification_status': 0, 'group_id': 0,
            'schedule_active': False, 'schedule_time': None
        }
        
        task = asyncio.create_task(run_userbot(uid, session_str, notify_user))
        user_tasks[uid] = task
        
        await msg.edit(f"✅ **Login Success!**\nWelcome, {me.first_name}.")
        
    except Exception as e:
        await msg.edit(f"❌ Error: {e}")

@master.on(events.NewMessage(pattern='/login'))
async def otp_login(event):
    sender = event.sender_id
    if sender in user_configs: return await event.reply("Already logged in.")
    
    async with master.conversation(sender) as conv:
        await conv.send_message("Send Phone Number:")
        try: phone = (await conv.get_response()).text
        except: return
        
        client = TelegramClient(StringSession(), API_ID, API_HASH)
        await client.connect()
        try:
            await client.send_code_request(phone)
            await conv.send_message("Send OTP (format: 1 2 3 4 5):")
            otp = (await conv.get_response()).text.replace(" ", "")
            await client.sign_in(phone, otp)
        except SessionPasswordNeededError:
            await conv.send_message("Two-Step Password:")
            pwd = (await conv.get_response()).text
            await client.sign_in(password=pwd)
        except Exception as e:
            return await conv.send_message(f"Error: {e}")
            
        sess = client.session.save()
        cursor = db.conn.cursor()
        now = datetime.now().isoformat()
        cursor.execute("INSERT OR REPLACE INTO users (user_id, session, poke_list, ball, start_time, interval) VALUES (?, ?, ?, ?, ?, ?)", 
                       (sender, sess, json.dumps(DEFAULT_LIST), "Safari Ball", now, DEFAULT_INTERVAL))
        db.conn.commit()
        
        user_configs[sender] = {
            'list': DEFAULT_LIST, 'ball': "Safari Ball", 
            'hunting': False, 'mode': 'STOPPED', 'interval': DEFAULT_INTERVAL,
            'stats': {'total_caught': 0, 'total_fled': 0, 'total_matched': 0, 'total_shiny': 0},
            'notification_status': 0, 'group_id': 0,
            'schedule_active': False, 'schedule_time': None
        }
        
        task = asyncio.create_task(run_userbot(sender, sess, notify_user))
        user_tasks[sender] = task
        await conv.send_message("✅ **Logged in!**")

# ================= ADMIN/OWNER COMMANDS =================

@master.on(events.NewMessage(pattern='/stats'))
async def global_stats(event):
    if event.sender_id != OWNER_ID: return
    
    total_users = len(user_configs)
    active_users = sum(1 for u in user_configs.values() if u['hunting'])
    total_caught = sum(u['stats']['total_caught'] for u in user_configs.values())
    
    msg = (f"≡ **Global Admin Stats**\n"
           f"━━━━━━━━━━━━━━━━━━\n"
           f"» **Total Users:** {total_users}\n"
           f"» **Active Hunters:** {active_users}\n"
           f"» **Total Catches:** {total_caught}")
    await event.reply(msg)

@master.on(events.NewMessage(pattern='/allsafari'))
async def force_start_all(event):
    if event.sender_id != OWNER_ID: return
    count = 0
    for uid, config in user_configs.items():
        if not config['hunting']:
            config['hunting'] = True
            config['mode'] = 'SAFARI_INIT'
            count += 1
            if uid in user_clients:
                asyncio.create_task(auto_enter_loop(user_clients[uid], uid))
    await event.reply(f"🚀 **Force Started:** {count} bots.")

@master.on(events.NewMessage(pattern='/allexit'))
async def force_stop_all(event):
    if event.sender_id != OWNER_ID: return
    count = 0
    for config in user_configs.values():
        if config['hunting']:
            config['hunting'] = False
            config['mode'] = 'STOPPED'
            count += 1
    await event.reply(f"🛑 **Force Stopped:** {count} bots.")

@master.on(events.NewMessage(pattern='/log'))
async def get_log(event):
    if event.sender_id != OWNER_ID: return
    if os.path.exists(LOG_FILE):
        await event.reply(file=LOG_FILE, message="📄 **System Log File**")
    else:
        await event.reply("(!) Log file empty or missing.")

@master.on(events.NewMessage(pattern='/fullexport'))
async def backup_db(event):
    if event.sender_id != OWNER_ID: return
    cursor = db.conn.cursor()
    cursor.execute("SELECT * FROM users")
    columns = [description[0] for description in cursor.description]
    rows = cursor.fetchall()
    data = [dict(zip(columns, row)) for row in rows]
    json_data = json.dumps(data, indent=4)
    zip_buffer = io.BytesIO()
    with zipfile.ZipFile(zip_buffer, "w", zipfile.ZIP_DEFLATED) as zip_file:
        zip_file.writestr("hexabot_data.json", json_data)
    zip_buffer.seek(0)
    zip_buffer.name = f"backup_{datetime.now().strftime('%Y%m%d')}.zip"
    await event.reply("💾 **Database Backup:**", file=zip_buffer)

@master.on(events.NewMessage(pattern='/fullimport'))
async def restore_db(event):
    if event.sender_id != OWNER_ID: return
    if not event.is_reply: return await event.reply("(!) Reply to a ZIP file.")
    reply = await event.get_reply_message()
    if not reply.document: return await event.reply("(!) No file found.")
    msg = await event.reply("⏳ Restoring...")
    try:
        file_bytes = await reply.download_media(bytes)
        with zipfile.ZipFile(io.BytesIO(file_bytes)) as z:
            with z.open("hexabot_data.json") as f:
                users = json.load(f)
        for t in user_tasks.values(): t.cancel()
        cursor = db.conn.cursor()
        count = 0
        for u in users:
            cursor.execute("""INSERT OR REPLACE INTO users 
                              (user_id, session, poke_list, ball, total_matched, total_caught, total_fled, total_shiny, start_time, notification_status, group_id, interval, schedule_time, schedule_active) 
                              VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""", 
                           (u['user_id'], u['session'], u['poke_list'], u['ball'], 
                            u['total_matched'], u['total_caught'], u['total_fled'], u.get('total_shiny', 0),
                            u['start_time'], u['notification_status'], u['group_id'], u.get('interval', 2.5),
                            u.get('schedule_time'), u.get('schedule_active', 0)))
            count += 1
            task = asyncio.create_task(run_userbot(u['user_id'], u['session'], notify_user))
            user_tasks[u['user_id']] = task
        db.conn.commit()
        await msg.edit(f"✅ **Restored {count} users successfully.**")
    except Exception as e:
        await msg.edit(f"❌ Restore Failed: {e}")

# --- SCHEDULER TASK ---
async def global_scheduler():
    logger.info("Scheduler started.")
    while True:
        # Check every 60 seconds
        now = datetime.now(IST)
        current_time_str = now.strftime("%I:%M %p") # 10:00 AM
        
        # 1. Reset Daily Stats at 5 AM
        if now.hour == 5 and now.minute == 0:
            db.reset_daily_stats()
            # Wait a minute so we don't trigger multiple times
            await asyncio.sleep(60)
            continue
            
        # 2. Check each user's schedule
        for uid, config in user_configs.items():
            if config.get('schedule_active') and config.get('schedule_time') == current_time_str:
                # Only start if not already running
                if not config.get('hunting'):
                    config['hunting'] = True
                    config['mode'] = 'SAFARI_INIT'
                    if uid in user_clients:
                        asyncio.create_task(auto_enter_loop(user_clients[uid], uid))
                        try: await master.send_message(uid, f"⏰ **Schedule Triggered!**\nAuto-started at {current_time_str}")
                        except: pass
        
        # Sleep until the start of the next minute
        await asyncio.sleep(60 - datetime.now().second)

# --- MAIN LOOP ---
async def main():
    # Load Users
    users = db.load_users()
    print(f"Loaded {len(users)} users.")
    
    for u in users:
        uid = u['user_id']
        try:
            task = asyncio.create_task(run_userbot(uid, u['session'], notify_user))
            user_tasks[uid] = task
        except Exception as e:
            logger.error(f"Failed to start user {uid}: {e}")

    # Start Scheduler
    asyncio.create_task(global_scheduler())

    print("Master Bot Started...")
    await master.run_until_disconnected()

if __name__ == '__main__':
    master.loop.run_until_complete(main())

