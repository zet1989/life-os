import asyncio, sys, os
sys.path.insert(0, '/app')
os.chdir('/app')

async def test():
    from src.db.postgres import init_pool
    await init_pool()
    
    from src.bots.master.scheduler import sync_todoist_inbox
    
    class FakeBot:
        async def send_message(self, chat_id, text, **kw):
            print(f"SEND to {chat_id}: {text[:200]}")
    
    print("Running sync_todoist_inbox...")
    await sync_todoist_inbox(FakeBot())
    print("Done!")
    
    # Check table after
    from src.db.queries import get_synced_todoist_ids, get_admin_users
    admins = await get_admin_users()
    uid = admins[0]["user_id"]
    known = await get_synced_todoist_ids(uid)
    print(f"known_ids after sync: {len(known)} entries")

asyncio.run(test())
