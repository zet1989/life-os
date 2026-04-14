import asyncio, sys, os
sys.path.insert(0, '/app')
os.chdir('/app')

async def check():
    from src.db.postgres import init_pool
    await init_pool()
    
    from src.integrations.todoist import get_tasks, get_inbox_project_id
    inbox_id = await get_inbox_project_id()
    print('Inbox project_id:', inbox_id)
    
    all_tasks = await get_tasks()
    print('All tasks (no project filter):', len(all_tasks))
    
    inbox_tasks = await get_tasks(project_id=inbox_id)
    print('Inbox tasks:', len(inbox_tasks))
    
    # Show project_ids
    pids = {}
    for t in all_tasks:
        pid = t.get('project_id', '?')
        pids[pid] = pids.get(pid, 0) + 1
    print('Tasks per project_id:')
    for pid, cnt in sorted(pids.items(), key=lambda x: -x[1]):
        print(f'  {pid}: {cnt} tasks')

asyncio.run(check())
