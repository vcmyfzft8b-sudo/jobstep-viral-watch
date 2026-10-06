"""State kept between runs (committed to the `state` branch by the workflow).

state/videos.json   videos still on the watchlist: snapshots, notified levels, format
state/history.json  every video ever seen, final numbers + format (used for ranking and creator baselines)
state/log.json      what the watcher did (alerts, pages built)
"""
import json
import os
import time

DIR = os.environ.get('STATE_DIR', 'state')


def _path(name):
    return os.path.join(DIR, name)


def load(name, default):
    try:
        with open(_path(name)) as f:
            return json.load(f)
    except FileNotFoundError:
        return default


def save(name, data):
    os.makedirs(DIR, exist_ok=True)
    tmp = _path(name) + '.tmp'
    with open(tmp, 'w') as f:
        json.dump(data, f, ensure_ascii=False, indent=1, sort_keys=True)
    os.replace(tmp, _path(name))


def log(entry):
    entries = load('log.json', [])
    entries.append({'ts': int(time.time()), **entry})
    save('log.json', entries[-2000:])
