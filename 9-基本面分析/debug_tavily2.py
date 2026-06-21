import urllib.request
import json

api_key = "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"
url = "https://api.tavily.com/search"
query = (
    "Search Polymarket for Bitcoin price prediction probabilities. "
    "Find the 'Yes' probability for Bitcoin to reach $100k or end the year/month higher. "
    "Summarize the probabilities for near-term (e.g. this month), mid-term (e.g. next month or quarter), and far-term (e.g. end of year). "
    "Return ONLY a JSON object with keys 'near', 'mid', 'far' containing float values between 0.0 and 1.0 representing the bullish probabilities. Example: {\"near\": 0.45, \"mid\": 0.60, \"far\": 0.80}"
)
payload = {
    "api_key": api_key,
    "query": query,
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
