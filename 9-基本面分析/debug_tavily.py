import urllib.request
import json

api_key = "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"
url = "https://api.tavily.com/search"
payload = {
    "api_key": api_key,
    "query": "Test search",
    "search_depth": "advanced",
    "include_answer": True
}
req = urllib.request.Request(url, data=json.dumps(payload).encode('utf-8'), headers={"Content-Type": "application/json"})
try:
    with urllib.request.urlopen(req) as response:
        print(response.read().decode('utf-8'))
except urllib.error.HTTPError as e:
    print(e.code)
    print(e.read().decode('utf-8'))
