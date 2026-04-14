import urllib.request
import json

token = "eb421296d783159926a89c75ca1b3e192bf0ce6d"
headers = {"Authorization": "Bearer " + token}

endpoints = [
    "https://api.todoist.com/api/v1/tasks?limit=3",
    "https://api.todoist.com/api/v1/projects?limit=3",
]

for url in endpoints:
    req = urllib.request.Request(url, headers=headers)
    try:
        resp = urllib.request.urlopen(req)
        data = resp.read()[:500].decode()
        print(f"OK {resp.status}: {url}")
        print(data)
    except urllib.error.HTTPError as e:
        body = e.read()[:300].decode()
        print(f"ERR {e.code}: {url}")
        print(body)
    print("---")
