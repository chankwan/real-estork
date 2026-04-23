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
print('Main page status:', resp.status_code)

html = resp.text
payload = None
raw_match = re.search(r'raw=\"([^\"]+)\".+?prid=\"(\d+)\"', html)
if raw_match:
    payload = {
        'raw': raw_match.group(1),
        'prid': raw_match.group(2),
        'uid': ''
    }
print('Found test payload:', payload)

if payload:
    form_data = {
        'PhoneNumber': payload['raw'],
        'createLead[sellerId]': payload['uid'],
        'createLead[productId]': payload['prid'],
        'createLead[productType]': '0',
        'createLead[leadSourcePage]': 'BDS_SEARCH_RESULT_PAGE',
        'createLead[leadSourceAction]': 'PHONE_REVEAL',
        'createLead[fromLeadType]': 'AGENT_LISTING',
    }
    
    headers = {
        'Origin': 'https://batdongsan.com.vn',
        'Referer': 'https://batdongsan.com.vn/cho-thue-nha-mat-pho-tp-hcm',
        'X-Requested-With': 'XMLHttpRequest',
    }
    
    dec_resp = session.post(
        'https://batdongsan.com.vn/microservice-architecture-router/Product/ProductDetail/DecryptPhone',
        data=form_data,
        headers=headers,
        timeout=15
    )
    print('Decrypt status:', dec_resp.status_code)
    print('Decrypt body:', dec_resp.text)
