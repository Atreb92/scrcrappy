from scrcrappy.keyqueue import KeyQueue


def run(q):
    while q.drain():
        pass


def test_type_text_sends_down_up_pairs_in_order():
    sent = []
    q = KeyQueue(lambda m, k: sent.append((m, k)))
    assert q.type_text("aZ") == 0
    run(q)
    assert sent == [(0, [0x04]), (0, []), (0x02, [0x1D]), (0, [])]


def test_live_key_during_paste_goes_after_it():
    sent = []
    q = KeyQueue(lambda m, k: sent.append((m, k)))
    q.type_text("ab")
    q.drain()  # paste under way
    q.report(0, [0x06])
    run(q)
    assert sent == [(0, [0x04]), (0, []), (0, [0x05]), (0, []), (0, [0x06])]


def test_type_text_reports_skipped():
    q = KeyQueue(lambda m, k: None)
    assert q.type_text("è!") == 1
