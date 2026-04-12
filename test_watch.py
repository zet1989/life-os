import urllib.request, json
data = json.dumps({"heart_rate": 72}).encode()
req = urllib.request.Request("http://localhost:8443/api/watch/push", data=data, method="POST")
req.add_header("Authorization", "Bearer wk_0881039935c24045b4fa7e392bd441da")
req.add_header("Content-Type", "application/json")
resp = urllib.request.urlopen(req)
print(resp.read().decode())
