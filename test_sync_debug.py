"""Test todoist sync manually and check scheduler jobs."""
import asyncio, sys, os
sys.path.insert(0, '/app')
os.chdir('/app')

async def test():
    from src.db.postgres import init_pool
    await init_pool()
    
    from src.db.queries import get_synced_todoist_ids, get_admin_users
    admins = await get_admin_users()
    uid = admins[0]["user_id"]
    known = await get_synced_todoist_ids(uid)
    print(f"known_ids in DB: {len(known)}")
    
    from src.integrations.todoist import get_inbox_tasks
    tasks = await get_inbox_tasks()
    print(f"todoist inbox tasks: {len(tasks)}")
    
    new_tasks = [t for t in tasks if t.get("id", "") not in known]
    print(f"new (not synced) tasks: {len(new_tasks)}")
    if new_tasks:
        for t in new_tasks[:5]:
            print(f"  NEW: {t.get('content','?')} (id={t.get('id','')})")

    # Manual sync
    from src.bots.master.scheduler import sync_todoist_inbox
    class FakeBot:
        async def send_message(self, chat_id, text, **kw):
            print(f"BOT_SEND to {chat_id}: {text[:300]}")
    
    print("\nRunning sync_todoist_inbox()...")
    await sync_todoist_inbox(FakeBot())
    print("Done!")
    
    known2 = await get_synced_todoist_ids(uid)
    print(f"known_ids after: {len(known2)}")

asyncio.run(test())
