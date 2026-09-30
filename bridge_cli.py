"""Local blocking wait on the bridge; only real incoming events reach the agent."""
import argparse
import json
import time
from pathlib import Path
from listener import BASE, STATE, write_json, load_config


def current_request(directory, request_id=None):
    path = directory/'request.json'
    if not path.exists():
        return None
    request = json.loads(path.read_text(encoding='utf-8-sig'))
    if request.get('status') != 'pending' or (request_id and request.get('request_id') != request_id):
        return None
    status_path = STATE/'status.json'
    if not status_path.exists() or time.time()-status_path.stat().st_mtime > 10:
        return None
    status = json.loads(status_path.read_text(encoding='utf-8-sig'))
    if status.get('status') != '监听中，仅生成草稿' or status.get('contact') != request['contact'] or status.get('revision') != request['revision']:
        return None
    return request


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=['wait', 'respond', 'check'])
    parser.add_argument('--after', default='')
    parser.add_argument('--timeout', type=float, default=600)
    parser.add_argument('--request-id')
    parser.add_argument('--reply-file', type=Path)
    args = parser.parse_args()
    config = load_config()
    directory = BASE/config.get('bridge_dir', 'bridge')
    if args.action == 'wait':
        deadline = time.monotonic()+args.timeout
        while time.monotonic() < deadline:
            try:
                request = current_request(directory)
                if request and request['request_id'] != args.after:
                    print(json.dumps(request, ensure_ascii=False))
                    return
            except (OSError, ValueError, KeyError):
                pass
            time.sleep(1)
        print('{"status":"timeout"}')
        return
    if not args.request_id:
        parser.error('--request-id is required')
    request = current_request(directory, args.request_id)
    if not request:
        raise SystemExit('STALE: 请求已取消、对话变化、监听暂停或心跳过期')
    if args.action == 'check':
        print(json.dumps(request, ensure_ascii=False))
        return
    if not args.reply_file:
        parser.error('--reply-file is required')
    reply = json.loads(args.reply_file.read_text(encoding='utf-8-sig'))
    if not isinstance(reply, dict) or set(reply) != {'reply_text', 'sticker_suggestion'} or not all(isinstance(v, str) for v in reply.values()):
        raise SystemExit('Invalid reply schema')
    write_json(directory/'response.json', dict(request_id=args.request_id, reply=reply))
    print('已回传草稿，未发送微信消息')


if __name__ == '__main__':
    main()
