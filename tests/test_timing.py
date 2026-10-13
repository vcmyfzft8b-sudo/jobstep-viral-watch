from watcher import timing


def test_share_maps_to_the_example_timeline():
    segs = [{'start': 0, 'end': 4, 'text': 'one two three four'}, {'start': 10, 'end': 14, 'text': 'five six seven eight'}]
    assert timing._at_share(segs, 0.5) == 4
    assert timing._at_share(segs, 0.75) == 12


def test_exact_brand_moment_in_the_example():
    segs = [{'start': 0, 'end': 5, 'text': 'Hola a todos.'}, {'start': 5, 'end': 10, 'text': 'Entra en JobStep ahora.'}]
    assert 5 < timing._brand_said(segs, own=False) < 10
    assert timing._brand_said(segs, own=True) is None
