import asyncio
import re
import os
import functools
from random import uniform
from telethon import TelegramClient, events
from telethon.sessions import StringSession
from config import *
from database import update_stat

# Helper for non-blocking file and DB operations
async def run_sync(func, *args):
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(None, functools.partial(func, *args))

async def robust_click(client, chat_id, msg_id, text_to_click):
    """Retries clicking a button safely."""
    attempt = 1
    while attempt <= 3:
        try:
            msg = await client.get_messages(chat_id, ids=msg_id)
            if not msg or not msg.reply_markup: return False
            
            # Find button index
            target_index = -1
            all_buttons = [b for row in msg.reply_markup.rows for b in row.buttons]
            for i, btn in enumerate(all_buttons):
                if text_to_click.lower() in btn.text.lower():
                    target_index = i
                    break
            
            if target_index == -1: return False
            
            await msg.click(target_index)
            return True
        except Exception:
            await asyncio.sleep(0.5)
            attempt += 1
    return False

async def send_hunt_loop(client, chat_id, user_id):
    """The main loop that sends /hunt."""
    try:
        entity = await client.get_entity(chat_id)
        target_id = entity.id
    except: return

    while True:
        # 1. Connection Safety Check
        if not client.is_connected():
            logger.warning(f"[LOOP] User {user_id} disconnected. Stopping loop.")
            return

        # 2. Config Checks
        if user_id not in user_configs: return
        config = user_configs[user_id]
        if not config.get('hunting'): return 
        
        # Double check mode before acting
        if config.get('mode') == 'ENGAGED': 
            await asyncio.sleep(1)
            continue

        try:
            # 3. Check Last Message for "Wait"
            # Get 2 messages in case the very last one is our own /hunt that hasn't been replied to yet
            msgs = await client.get_messages(chat_id, limit=2)
            should_skip = False
            
            for msg in msgs:
                if msg.sender_id == target_id:
                    text_lower = msg.raw_text.lower()
                    
                    # Regex to find specific wait time
                    wait_match = re.search(r"wait\s+(\d+)\s+second", text_lower)
                    if wait_match:
                        seconds = int(wait_match.group(1))
                        # Add a random buffer to look human
                        sleep_time = seconds + uniform(1.5, 3.0) 
                        logger.info(f"[WAIT] {user_id} sleeping for {sleep_time:.2f}s")
                        await asyncio.sleep(sleep_time)
                        should_skip = True
                        break
                    elif "wait" in text_lower and "second" in text_lower:
                        # Fallback if regex fails but keyword exists
                        await asyncio.sleep(uniform(5, 10))
                        should_skip = True
                        break
            
            if should_skip: continue

            # 4. Send Hunt
            await client.send_message(chat_id, "/hunt")
            
            # 5. Wait for response (Variable Interval)
            user_interval = config.get('interval', DEFAULT_INTERVAL)
            
            # Smart wait: check repeatedly if mode changed to ENGAGED (e.g., by a spawn)
            slept = 0
            while slept < user_interval:
                if config.get('mode') == 'ENGAGED': break
                await asyncio.sleep(0.1)
                slept += 0.1
                
        except Exception as e:
            logger.error(f"[HUNT ERROR] {user_id}: {e}")
            await asyncio.sleep(5)

async def auto_enter_loop(client, uid):
    """Tries to enter the safari zone."""
    for i in range(5):
        config = user_configs.get(uid)
        if not config or not config.get('hunting') or config.get('mode') != 'SAFARI_INIT': 
            return
        
        try: await client.send_message(HEXA_ID, "/enter")
        except: pass
        await asyncio.sleep(5)

async def run_userbot(user_id, session_str, master_bot_callback):
    """Main process for a single user."""
    try:
        client = TelegramClient(StringSession(session_str), API_ID, API_HASH)
        await client.connect()
        
        if not await client.is_user_authorized():
            logger.error(f"User {user_id} session expired.")
            return

        user_clients[user_id] = client
    except Exception as e:
        logger.error(f"Connect fail {user_id}: {e}")
        return

    # --- EVENT HANDLERS ---
    @client.on(events.NewMessage(chats=HEXA_ID))
    @client.on(events.MessageEdited(chats=HEXA_ID))
    async def handler(event):
        config = user_configs.get(user_id)
        if not config: return
        
        text = event.raw_text
        text_lower = text.lower()
        msg_id = event.message.id

        # --- AUTO START ---
        if "welcome to the" in text_lower and "safari zone" in text_lower:
            config['hunting'] = True
            config['mode'] = 'SEARCHING'
            await master_bot_callback(user_id, "[+] **Safari Session Started!**")
            # Cancel old task if exists
            if user_id in user_tasks and not user_tasks[user_id].done():
                 # Logic to handle clean restart if needed, mostly fine to just start new loop
                 pass
            asyncio.create_task(send_hunt_loop(client, HEXA_ID, user_id))
            return
        
        if "already in the" in text_lower and "safari zone" in text_lower:
             if config.get('mode') == 'SAFARI_INIT':
                config['hunting'] = True
                config['mode'] = 'SEARCHING'
                asyncio.create_task(send_hunt_loop(client, HEXA_ID, user_id))
             return

        if not config.get('hunting'): return

        # --- STOPPERS ---
        if any(x in text_lower for x in ["already played", "limit reached", "out of safari balls", "game has finished"]):
            config['hunting'] = False
            config['mode'] = 'STOPPED'
            await master_bot_callback(user_id, f"[!] **Session Ended:**\n{text.splitlines()[0]}")
            return

        # --- CATCH LOGIC ---
        if "caught a wild" in text_lower:
            # Non-blocking DB call
            await run_sync(update_stat, user_id, 'total_caught')
            
            msg = text.splitlines()[0]
            if event.message.media:
                path = await client.download_media(event.message)
                await master_bot_callback(user_id, f"**{msg}**", path)
                await run_sync(os.remove, path)
            else:
                await master_bot_callback(user_id, f"**{msg}**")
            
            config['mode'] = 'SEARCHING'
            return

        # --- BATTLE/CATCH SCREEN ---
        is_battle = text.strip().startswith("Wild") or (event.message.reply_markup and "throw ball" in event.message.reply_markup.rows[0].buttons[0].text.lower())
        
        if is_battle:
            config['mode'] = 'ENGAGED'
            # Random delay before throwing to mimic human reaction
            await asyncio.sleep(uniform(2.0, 4.0))
            await robust_click(client, HEXA_ID, msg_id, "Throw Ball")
            return

        # --- SPAWN DETECTION ---
        match = re.search(r"wild\s+(.+?)\s+\(Lv", text, re.IGNORECASE)
        if match:
            name = match.group(1).strip()
            is_shiny = "✨" in text or "✨" in name
            
            should_catch = False
            if is_shiny:
                should_catch = True
                await run_sync(update_stat, user_id, 'total_shiny')
                await master_bot_callback(user_id, f"★ **SHINY DETECTED: {name}**")
            elif any(t.lower() in name.lower() for t in config['list']):
                should_catch = True
            
            if should_catch:
                await run_sync(update_stat, user_id, 'total_matched')
                config['mode'] = 'ENGAGED'
                await asyncio.sleep(uniform(0.5, 1.5))
                await robust_click(client, HEXA_ID, msg_id, "Engage")
            return

    try:
        await client.run_until_disconnected()
    except:
        pass
    finally:
        if client.is_connected(): await client.disconnect()

