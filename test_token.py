import json
import re
from curl_cffi import requests

try:
    with open('.batdongsan_cookies.json') as f:
        data = json.load(f)
    old_cookies = {c['name']: c['value'] for c in data.get('cookies', [])}
except Exception:
    old_cookies = {}

session = requests.Session(impersonate='firefox133')
for k,v in old_cookies.items():
    session.cookies.set(k, v, domain='.batdongsan.com.vn')

resp = session.get('https://batdongsan.com.vn/cho-thue-nha-mat-pho-tp-hcm', timeout=15)
match = re.search(r'accessToken[\"\':\s]+([a-zA-Z0-9\.\-\_]+)', resp.text, re.IGNORECASE)
if match:
    print('Found accessToken in HTML:', match.group(1)[:20] + '...')
else:
    print('No accessToken found in HTML')
    
print('Session cookies:', session.cookies.get_dict())
