# -*- coding: utf-8 -*-
"""Render bridge/request.json into a readable transcript for the agent.

Scope:
    The reply is produced by an *external agent* (CLI / IDE / chat assistant).
    This script only READS and FORMATS — it never generates, never sends, and
    never calls any model API.

用法：
    python session_view.py          # 渲染当前 pending 请求（含上下文与写作要求）
    python session_view.py --raw    # 输出原始 JSON
"""
import argparse
import json
import sys
from pathlib import Path

BASE = Path(__file__).resolve().parent

WHO = {'peer': '← contact', 'self': '→ you', 'unknown': '? unknown sender'}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--raw', action='store_true', help='输出原始 JSON')
    args = ap.parse_args()

    config = json.loads((BASE / 'config.json').read_text(encoding='utf-8-sig'))
    bridge_dir = BASE / config.get('bridge_dir', 'bridge')
    path = bridge_dir / 'request.json'

    if not path.exists():
        print('没有 request.json —— 监听未启动，或尚无新消息。')
        return 1

    req = json.loads(path.read_text(encoding='utf-8-sig'))

    if args.raw:
        print(json.dumps(req, ensure_ascii=False, indent=2))
        return 0

    status = req.get('status')
    if status != 'pending':
        tail = ('｜原因：' + req['reason']) if req.get('reason') else ''
        print('当前请求状态 = %s（不是 pending，无需回复）%s' % (status, tail))
        return 0

    print('=' * 62)
    print('联系人: %s     revision: %s' % (req.get('contact'), req.get('revision')))
    print('request_id: %s' % req.get('request_id'))
    print('=' * 62)

    ctx = req.get('context') or []
    print('\n[Context] last %d messages — sender=self is you, peer is the contact:\n' % len(ctx))
    for m in ctx:
        who = WHO.get(m.get('sender'), m.get('sender'))
        kind = m.get('kind')
        tag = '' if kind == 'text' else '（%s · 内容未知，不可猜测）' % kind
        print('  %-12s %s%s' % (who, m.get('text', ''), tag))

    print('\n【本次写作要求】\n  %s' % (req.get('prompt') or '(无)'))

    print('\n【回传方式】（由本会话生成后执行）')
    print('  1) 写入 reply.json: {"reply_text":"...","sticker_suggestion":"..."}')
    print('  2) python bridge_cli.py respond --request-id %s --reply-file reply.json'
          % req.get('request_id'))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
