"""Claude via OpenRouter (OPENROUTER_API_KEY)."""
import base64
import json
import os
import re
import time

import requests

URL = 'https://openrouter.ai/api/v1/chat/completions'


def chat(model, system, content, max_tokens=8000, temperature=0.3):
    """content: str or list of OpenAI-style parts (text / image_url). Returns the reply text."""
    headers = {'Authorization': 'Bearer ' + os.environ['OPENROUTER_API_KEY'], 'Content-Type': 'application/json',
               'X-Title': 'jobstep-viral-watch'}
    body = {'model': model, 'max_tokens': max_tokens, 'temperature': temperature,
            'messages': [{'role': 'system', 'content': system}, {'role': 'user', 'content': content}]}
    for attempt in range(4):
        r = requests.post(URL, headers=headers, json=body, timeout=600)
        if r.status_code == 200:
            return r.json()['choices'][0]['message']['content']
        if r.status_code in (429, 500, 502, 503, 504):
            time.sleep(10 * (attempt + 1))
            continue
        raise RuntimeError(f'OpenRouter HTTP {r.status_code}: {r.text[:300]}')
    raise RuntimeError('OpenRouter: too many retries')


def chat_json(model, system, content, **kw):
    """Same as chat(), but parses the first JSON object in the reply."""
    text = chat(model, system, content, **kw)
    m = re.search(r'```(?:json)?\s*(\{.*\})\s*```', text, re.S) or re.search(r'(\{.*\})', text, re.S)
    if not m:
        raise ValueError('No JSON in model reply: ' + text[:300])
    return json.loads(m.group(1))


def image_part(path):
    with open(path, 'rb') as f:
        return {'type': 'image_url', 'image_url': {'url': 'data:image/jpeg;base64,' + base64.b64encode(f.read()).decode()}}
