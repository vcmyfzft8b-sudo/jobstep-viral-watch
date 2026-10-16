"""When is a JobStep video "taking off" or "viral"? Thresholds live in config.json.

Taking off (early warning): within its first 6 / 24 / 48 hours a video has 5k / 20k / 50k views,
or (within 72h) at least 10x its creator's usual views and 5k+.
Rising (user's choice, 15 Oct 2026): 30k+ views within its first 24 hours - in our data 4 of 5 such videos reached
100k and every 100k video got there. A NEW format (or an archived one) is built and listed right away (one Slack
ping, none again at 100k); a video of a live format gets its Slack ping only at 100k as before.
Viral (confirmed): 100k+ views within the watch window (7 days).
Converting (user's rule, 16 Oct 2026): below the viral bar, but many viewers save it (conversion.converting, e.g. 30k+
views and 2%+ saved - more in a market that saves more). Handled like rising.
Saves (16 Oct 2026, replaces the shares+saves 1.5% rule): a viral / rising video that too few viewers save for its
market (conversion.too_few_saves) or a paid ad still alerts and counts for its format, but never builds or brings
back a format.
"""
import statistics


def creator_baseline(history, handle):
    """Median views of the creator's videos that are at least 7 days old (None if too few)."""
    views = [v['views'] for v in history.values() if v['handle'] == handle and v.get('mature')]
    return statistics.median(views) if len(views) >= 5 else None


def engagement(video):
    return (video['shares'] + video['saves']) / max(video['views'], 1)


def level(video, now, baseline, th, cfg=None, typical_rate=None):
    """Returns 'viral', 'converting', 'rising', 'taking_off' or None (cfg: the whole config, for the conversion
    settings; typical_rate: the typical save rate of the video's market)."""
    from . import conversion
    age_h = (now - video['created']) / 3600
    views = video['views']
    if views >= th['viral_views']:
        return 'viral'
    if cfg is not None and conversion.converting(video, cfg, typical_rate):
        return 'converting'
    for hours, min_views in th.get('rising', []):
        if age_h <= hours and views >= min_views and 'rising' not in video.get('notified', []):
            return 'rising'
    for hours, min_views in th['early']:
        if age_h <= hours and views >= min_views:
            return 'taking_off'
    if (baseline and age_h <= th['creator_multiple_max_age_hours']
            and views >= th['creator_multiple_min_views'] and views >= th['creator_multiple'] * baseline):
        return 'taking_off'
    return None
