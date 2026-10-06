"""Claude through Claude Code on the user's Claude subscription (no API key).

GitHub Actions authenticates with CLAUDE_CODE_OAUTH_TOKEN (created once with `claude setup-token`).
Images are passed as files that Claude reads with its Read tool.
"""
import json
import os
import re
import shutil
import subprocess
import tempfile
import time

MODELS = {'anthropic/claude-opus-5.5': 'opus', 'anthropic/claude-sonnet-5.5': 'sonnet', 'opus': 'opus', 'sonnet': 'sonnet'}


def image_part(path):
    return {'type': 'image', 'path': path}


def chat(model, system, content, max_tokens=None, temperature=None, timeout=1800):
    """content: str or a list of {'type': 'text', 'text'} / {'type': 'image', 'path'} parts. Returns the reply text."""
    parts = [{'type': 'text', 'text': content}] if isinstance(content, str) else content
    work = tempfile.mkdtemp(prefix='claude-')
    try:
        prompt, images = [], 0
        for p in parts:
            if p['type'] == 'text':
                prompt.append(p['text'])
            else:
                images += 1
                name = f'image_{images:02d}.jpg'
                shutil.copy(p['path'], os.path.join(work, name))
                prompt.append(f'[Bild: {name}]')
        text = '\n'.join(prompt)
        if images:
            text = (f'Es gibt {images} Bilddateien im aktuellen Ordner ([Bild: …] markiert, wo sie hingehören). '
                    'Lies zuerst JEDE Bilddatei mit dem Read-Tool und schau sie dir an, bevor du antwortest.\n\n' + text)
        cmd = ['claude', '-p', '--model', MODELS.get(model, model), '--output-format', 'json',
               '--append-system-prompt', system, '--max-turns', str(10 + images * 2),
               '--allowedTools', 'Read', '--disallowedTools', 'Bash', 'Edit', 'Write', 'WebFetch', 'WebSearch']
        for attempt in range(3):
            r = subprocess.run(cmd, input=text, capture_output=True, text=True, cwd=work, timeout=timeout)
            try:
                out = json.loads(r.stdout)
            except json.JSONDecodeError:
                out = {'is_error': True, 'result': (r.stderr or r.stdout)[-500:]}
            if not out.get('is_error') and out.get('result'):
                return out['result']
            err = str(out.get('result') or out)[:300]
            if re.search(r'limit|overloaded|529|rate', err, re.I) and attempt < 2:
                time.sleep(60 * (attempt + 1))
                continue
            raise RuntimeError('Claude Code: ' + err)
        raise RuntimeError('Claude Code: too many retries')
    finally:
        shutil.rmtree(work, ignore_errors=True)


def chat_json(model, system, content, **kw):
    """Same as chat(), but parses the first JSON object in the reply."""
    text = chat(model, system + '\nAntworte nur mit dem JSON-Objekt.', content, **kw)
    m = re.search(r'```(?:json)?\s*(\{.*\})\s*```', text, re.S) or re.search(r'(\{.*\})', text, re.S)
    if not m:
        raise ValueError('No JSON in model reply: ' + text[:300])
    return json.loads(m.group(1))
