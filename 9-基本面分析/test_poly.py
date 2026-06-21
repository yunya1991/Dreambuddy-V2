import urllib.request
import json
req = urllib.request.Request("https://gamma-api.polymarket.com/events?limit=2&closed=false&search=bitcoin")
try:
    data = json.loads(urllib.request.urlopen(req, timeout=10).read().decode('utf-8'))
    print(json.dumps(data, indent=2)[:500])
except Exception as e:
    print("Error:", e)
