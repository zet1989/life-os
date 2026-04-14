import asyncio, sys, os
sys.path.insert(0, '/app')
os.chdir('/app')

async def test():
    from src.db.postgres import get_pool, init_pool
    from src.config import settings
    
    # Init pool
    await init_pool()
    
    # Test todoist
    from src.integrations.todoist import is_configured, get_inbox_tasks
    print("configured:", is_configured())
    
    tasks = await get_inbox_tasks()
    print("tasks count:", len(tasks))
    if tasks:
        print("first task:", tasks[0].get("content", "?"))
    
    # Test query
    from src.db.queries import get_synced_todoist_ids, get_admin_users
    admins = await get_admin_users()
    print("admins:", admins)
    if admins:
        uid = admins[0]["user_id"]
        known = await get_synced_todoist_ids(uid)
        print("known_ids:", known)

asyncio.run(test())
