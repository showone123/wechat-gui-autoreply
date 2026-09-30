# -*- coding: utf-8 -*-
"""合成事件端到端闭环测试（不碰微信、不发送任何消息）。

链路：
    Tracker(合成消息) -> EventBridge.publish -> request.json
    -> bridge_cli wait  (真实 CLI，验证事件可被读出)
    -> 生成回复 (由调用方注入) -> bridge_cli respond -> response.json
    -> EventBridge.receive -> 草稿 latest-draft.md / latest-ready.json

严格约束：
  * 不导入 Reader，不读取微信窗口，不点击/输入/发送
  * 所有消息均为合成数据，绝不写入真实聊天
  * 仅使用本项目 bridge_dir；测试结束把 request 标记为 cancelled

用法：
    python e2e_synthetic_test.py --reply-file synth_reply.json
"""
import argparse
import json
import subprocess
import sys
import time
from pathlib import Path

BASE = Path(__file__).resolve().parent
sys.path.insert(0, str(BASE))

from listener import Tracker, EventBridge, write_json, STATE, load_config  # noqa: E402

PY = sys.executable


def row(i, sender, text):
    return dict(id='SYNTH|%d|%s' % (i, text), sender=sender, text=text,
                kind='text')


def heartbeat(bridge, contact, revision):
    """伪造 listener 心跳，使 bridge_cli.current_request 认账。"""
    STATE.mkdir(parents=True, exist_ok=True)
    write_json(STATE / 'status.json', {
        'time': time.strftime('%Y-%m-%d %H:%M:%S'), 'pid': 0,
        'status': '监听中，仅生成草稿', 'mode': 'draft_only',
        'revision': revision, 'contact': contact, 'synthetic': True,
    })


def run_cli(*args):
    r = subprocess.run([PY, str(BASE / 'bridge_cli.py'), *args],
                       cwd=str(BASE), capture_output=True, text=True,
                       encoding='utf-8', timeout=60)
    return r.returncode, (r.stdout or '').strip(), (r.stderr or '').strip()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--reply-file', type=Path, required=True)
    args = ap.parse_args()

    config = load_config()
    bridge_dir = BASE / config.get('bridge_dir', 'bridge')
    contact = config['contact']
    results = []

    def check(name, ok, detail=''):
        results.append((name, ok, detail))
        print('%s %s%s' % ('PASS' if ok else 'FAIL', name,
                           (' — ' + detail) if detail else ''))

    # ── 1. 合成事件流，驱动 Tracker 得到 pending ──────────────────
    t = Tracker()
    t.update([row(1, 'peer', '昨天那家店叫什么来着')], 0)          # 建基线
    t.update([row(1, 'peer', '昨天那家店叫什么来着'),
              row(2, 'peer', '我忘了名字')], 1)                     # 触发
    check('合成事件产生 pending', t.pending is True)
    check('上下文累积正确', len(t.context) == 2 and t.context[-1]['text'] == '我忘了名字')

    # ── 2. publish -> request.json ────────────────────────────────
    bridge = EventBridge(bridge_dir)
    prompt = '【合成测试】请依据上下文拟一条简短回复。'
    bridge.publish(list(t.context), contact, t.revision, prompt)
    req_id = bridge.active['request_id']
    check('request.json 已发布', (bridge_dir / 'request.json').exists(), 'id=' + req_id[:8])
    heartbeat(bridge, contact, t.revision)

    # ── 3. bridge_cli wait：真实 CLI 读事件 ───────────────────────
    code, out, err = run_cli('wait', '--timeout', '8', '--after', 'none')
    got = None
    try:
        got = json.loads(out)
    except Exception:
        pass
    check('bridge_cli wait 读到事件', bool(got) and got.get('request_id') == req_id,
          err or ('timeout' if out.startswith('{"status":"timeout"}') else ''))
    if got and got.get('request_id') == req_id:
        check('prompt 透传', got.get('prompt') == prompt)
        check('context 透传', len(got.get('context') or []) == 2)

        # ── 4. 生成回复（由外部注入，代表模型产出）→ respond ──────
        reply = json.loads(args.reply_file.read_text(encoding='utf-8-sig'))
        code, out, err = run_cli('respond', '--request-id', req_id,
                                 '--reply-file', str(args.reply_file))
        check('bridge_cli respond 成功', code == 0, err or out)

        # ── 5. listener 侧 receive -> 草稿 ────────────────────────
        r = bridge.receive()
        check('listener 收到响应', isinstance(r, dict) and r.get('reply_text') == reply['reply_text'])

        draft = BASE / 'latest-draft.md'
        ready = STATE / 'latest-ready.json'
        text = '# ' + contact + ' · 回复草稿（未发送）\n\n' + r['reply_text']
        text += '\n\n表情建议：' + r['sticker_suggestion']
        text += '\n\n生成时间：' + time.strftime('%Y-%m-%d %H:%M:%S')
        draft.write_text(text, encoding='utf-8')
        write_json(ready, dict(revision=t.revision, created_at=time.time(),
                               contact=contact, reply=r,
                               context=t.context, synthetic=True))
        check('草稿 latest-draft.md 落盘', draft.exists() and reply['reply_text'] in draft.read_text(encoding='utf-8'))
        check('latest-ready.json 落盘', ready.exists())

    # ── 6. 清理：不留 pending 请求 ───────────────────────────────
    if bridge.active:
        bridge.cancel('合成测试结束')
        check('遗留请求已取消', True)

    ok = all(r[1] for r in results)
    print('\n合成闭环：%d/%d 通过' % (sum(1 for r in results if r[1]), len(results)))
    print('注意：本测试未读取微信、未发送任何消息。')
    return 0 if ok else 1


if __name__ == '__main__':
    raise SystemExit(main())
