import re
ans = '{"near": 0.45, "mid": 0.60, "far": 0.80}'
near_m = re.search(r'near["\']?\s*:\s*([0-9.]+)', ans)
mid_m = re.search(r'mid["\']?\s*:\s*([0-9.]+)', ans)
far_m = re.search(r'far["\']?\s*:\s*([0-9.]+)', ans)
print('near:', near_m.group(1) if near_m else None)
print('mid:', mid_m.group(1) if mid_m else None)
print('far:', far_m.group(1) if far_m else None)
