from listener import Tracker

def row(i, sender='peer', text='同样的文字'):
    return dict(id=str(i), sender=sender, text=text, kind='text')

t = Tracker()
assert t.update([row(1)], 0) == 'baseline' and not t.pending
assert t.update([row(1)], 1) == 'unchanged'
assert t.update([row(1), row(2, 'self')], 2) == 'self_or_unknown' and not t.pending
assert t.update([row(1), row(2, 'self'), row(3)], 3) == 'incoming' and t.pending
revision = t.revision
assert t.update([row(2, 'self'), row(3)], 4) == 'unchanged' and t.revision == revision
assert t.update([row(2, 'self'), row(3), row(4)], 5) == 'incoming'
assert t.context[-2]['text'] == t.context[-1]['text'] and t.revision > revision
job_revision = t.revision
assert t.update([row(3), row(4), row(5, 'self')], 6) == 'self_or_unknown'
assert not t.pending and t.revision != job_revision  # model result is stale
t.update([row(4), row(5, 'self'), row(6, 'unknown')], 7)
assert not t.pending
t.pause()
system = row(7, 'self', '你撤回了一条消息')
system['kind'] = 'system'
assert t.update([row(6), system], 7.5) == 'baseline' and not t.pending
t.pause()
assert t.update([row(20)], 8) == 'baseline' and not t.pending
assert t.update([row(100)], 9) == 'baseline' and not t.pending  # lost overlap
assert len(t.context) <= 20
print('PASS: no trigger on baseline, self ignored, new incoming triggers, duplicate text still triggers, dedup, stale draft dropped, unknown sender skipped, resume rebuilds baseline')

import tempfile
import json
from pathlib import Path
from listener import EventBridge, write_json

with tempfile.TemporaryDirectory() as directory:
    d = Path(directory)
    b = EventBridge(d)
    b.publish([row(1)], 'example_contact', 1, 'test')
    first = b.active['request_id']
    reply = dict(reply_text='sure, on my way', sticker_suggestion='thumbs up')
    write_json(d/'response.json', dict(request_id='old', reply=reply))
    assert b.receive() is None
    write_json(d/'response.json', dict(request_id=first, reply={'reply_text': 1}))
    try:
        b.receive()
        raise AssertionError('bad schema accepted')
    except ValueError:
        pass
    write_json(d/'response.json', dict(request_id=first, reply=reply))
    assert b.receive() == reply and b.active is None
    b.publish([row(2)], 'example_contact', 2, 'test')
    b.cancel('self replied')
    assert b.receive() is None and json.loads((d/'request.json').read_text(encoding='utf-8'))['status'] == 'cancelled'
    b.publish([row(3)], 'another_contact', 3, 'test')
    EventBridge(d)
    assert json.loads((d/'request.json').read_text(encoding='utf-8'))['status'] == 'cancelled'
print('PASS: request published, stale result rejected, schema validated, draft returned, cancel and restart invalidation')

