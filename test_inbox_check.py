import asyncio, sys, os
sys.path.insert(0, '/app')
os.chdir('/app')

async def check():
    from src.db.postgres import init_pool
    await init_pool()
    
    import aiohttp
    from src.config import settings
    
    headers = {
        "Authorization": f"Bearer {settings.todoist_api_token}",
        "Content-Type": "application/json",
    }
    
    # Fetch ALL tasks with pagination
    all_tasks = []
    cursor = None
    for _ in range(20):
        params = {}
        if cursor:
            params["cursor"] = cursor
        async with aiohttp.ClientSession() as session:
            async with session.get(
                "https://api.todoist.com/api/v1/tasks",
                headers=headers, params=params,
            ) as resp:
                data = await resp.json()
                page = data.get("results", [])
                all_tasks.extend(page)
                cursor = data.get("next_cursor")
                print(f"Page: {len(page)} tasks, next_cursor: {cursor}")
                if not cursor:
                    break
    
    print(f"\nTotal tasks: {len(all_tasks)}")
    
    # Count by project
    pids = {}
    for t in all_tasks:
        pid = t.get("project_id", "?")
        pids[pid] = pids.get(pid, 0) + 1
    
    print("Tasks per project_id:")
    for pid, cnt in sorted(pids.items(), key=lambda x: -x[1]):
        print(f"  {pid}: {cnt}")
    
    # Check inbox
    from src.integrations.todoist import get_inbox_project_id
    inbox_id = await get_inbox_project_id()
    print(f"\nInbox project_id: {inbox_id}")
    inbox_count = pids.get(inbox_id, 0)
    print(f"Tasks in Inbox project: {inbox_count}")
    
    # Show inbox tasks
    inbox_tasks = [t for t in all_tasks if t.get("project_id") == inbox_id]
    for t in inbox_tasks[:10]:
        print(f"  - {t.get('content','?')}")

asyncio.run(check())
