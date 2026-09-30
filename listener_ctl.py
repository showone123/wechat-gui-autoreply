# -*- coding: utf-8 -*-
"""微信监听器的开关与状态查询。

用法（任意 Python 均可运行，只用标准库）：
    python listener_ctl.py status        # 在跑吗？
    python listener_ctl.py start         # 启动
    python listener_ctl.py stop          # 停止
    python listener_ctl.py restart       # 重启
    python listener_ctl.py contact       # 查看当前监听对象
    python listener_ctl.py contact 张三  # 热切换监听对象

状态判据（两路独立证据，避免误报）：
    1) state/status.json 存在且 mtime < 10 秒   → 心跳新鲜
    2) 该文件记录的 pid 仍在运行                 → 进程还活着
    两者同时成立才判「监听中」。
"""
import ctypes
import json
import os
import subprocess
import sys
import time
from pathlib import Path

BASE = Path(__file__).resolve().parent
STATE = BASE / 'state'
STATUS = STATE / 'status.json'
STOP = STATE / 'stop'
LISTENER_PY = BASE / 'listener.py'
def _find_runner():
    """Locate a pythonw.exe to host the background listener.

    Order: $WECHAT_LISTENER_PYTHON > pythonw beside the current interpreter > PATH.
    The interpreter must be the one that has the windows-mcp dependencies installed.
    """
    env = os.environ.get('WECHAT_LISTENER_PYTHON')
    if env and Path(env).exists():
        return Path(env)
    beside = Path(sys.executable).with_name('pythonw.exe')
    if beside.exists():
        return beside
    return Path('pythonw')


RUNNER = _find_runner()
HEARTBEAT_FRESH = 10.0

try:
    sys.stdout.reconfigure(encoding='utf-8')
except Exception:
    pass


# ── 进程工具（ctypes，不依赖 psutil） ────────────────────────────

def pid_alive(pid):
    """Windows 下不能对进程用 os.kill(pid, 0)——那会真的终止它。"""
    if not pid:
        return False
    PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
    STILL_ACTIVE = 259
    k = ctypes.windll.kernel32
    h = k.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, int(pid))
    if not h:
        return False
    try:
        code = ctypes.c_ulong()
        if k.GetExitCodeProcess(h, ctypes.byref(code)):
            return code.value == STILL_ACTIVE
        return False
    finally:
        k.CloseHandle(h)


def force_kill(pid):
    PROCESS_TERMINATE = 0x0001
    k = ctypes.windll.kernel32
    h = k.OpenProcess(PROCESS_TERMINATE, False, int(pid))
    if h:
        k.TerminateProcess(h, 1)
        k.CloseHandle(h)


# ── 状态探测 ────────────────────────────────────────────────────

def read_status():
    if not STATUS.exists():
        return None
    try:
        data = json.loads(STATUS.read_text(encoding='utf-8-sig'))
    except Exception:
        return None
    data['_age'] = time.time() - STATUS.stat().st_mtime
    return data


def probe():
    """返回 (running: bool, reason: str, data|None)"""
    st = read_status()
    if st is None:
        return False, '状态文件不存在（从未启动，或已被清理）', None
    if st.get('status') == '已停止':
        return False, '已正常停止（%s）' % st.get('time', '时间未知'), st
    if st['_age'] > HEARTBEAT_FRESH:
        return False, '心跳已过期 %.0f 秒，进程可能已死' % st['_age'], st
    if not pid_alive(st.get('pid')):
        return False, '心跳新鲜但 PID %s 已不存在' % st.get('pid'), st
    return True, '', st


# ── 子命令 ──────────────────────────────────────────────────────

def do_status():
    running, reason, st = probe()
    if not running:
        print('状态：未运行  [OFF]')
        print('  原因：%s' % reason)
        return 0
    age = st['_age']
    print('状态：监听中  [ON]')
    print('  PID        : %s' % st.get('pid'))
    print('  最后心跳   : %.0f 秒前（%s）' % (age, st.get('time')))
    print('  监听状态   : %s' % st.get('status'))
    print('  目标联系人 : %s' % st.get('contact'))
    print('  对话版本   : revision=%s' % st.get('revision'))
    if st.get('last_error'):
        print('  最近错误   : %s' % st['last_error'])
    note = st.get('last_sender')
    if note:
        print('  最新消息来自: %s' % note)
    return 0


def do_start():
    running, reason, st = probe()
    if running:
        print('已经在运行了，PID %s —— 不重复启动。' % st.get('pid'))
        return 0
    if not RUNNER.exists():
        print('找不到 pythonw：%s' % RUNNER)
        return 1
    if not LISTENER_PY.exists():
        print('找不到 listener.py：%s' % LISTENER_PY)
        return 1
    if not (BASE / 'config.json').exists() and not (BASE / 'config.example.json').exists():
        print('缺少 config.json —— 请先复制 config.example.json 并填写联系人。')
        return 1
    STATE.mkdir(parents=True, exist_ok=True)
    STOP.unlink(missing_ok=True)
    DETACHED_PROCESS = 0x00000008
    CREATE_NO_WINDOW = 0x08000000
    p = subprocess.Popen([str(RUNNER), str(LISTENER_PY)], cwd=str(BASE),
                         creationflags=DETACHED_PROCESS | CREATE_NO_WINDOW,
                         close_fds=True)
    for _ in range(24):
        time.sleep(0.5)
        running, _, st = probe()
        if running:
            print('已启动，PID %s。' % st.get('pid'))
            print('提示：监听要求微信在前台并停在目标对话底部。')
            return 0
    print('启动命令已发出（PID %s），但 12 秒内没看到心跳。' % p.pid)
    print('请再执行一次 status 复查；若仍无心跳，说明启动失败。')
    return 1


def do_stop():
    running, reason, st = probe()
    if not running:
        print('当前本来就没在运行（%s）。' % reason)
        STOP.unlink(missing_ok=True)
        return 0
    pid = st.get('pid')
    STATE.mkdir(parents=True, exist_ok=True)
    STOP.write_text('stop', encoding='utf-8')
    for _ in range(20):
        time.sleep(0.5)
        if not pid_alive(pid):
            print('已停止（PID %s 正常退出）。' % pid)
            STOP.unlink(missing_ok=True)
            return 0
    print('等待 10 秒仍未退出，强制结束 PID %s。' % pid)
    force_kill(pid)
    time.sleep(1)
    if pid_alive(pid):
        print('强制结束失败，请手动检查 PID %s。' % pid)
        return 1
    STOP.unlink(missing_ok=True)
    print('已强制停止。')
    return 0


def do_contact(name=None):
    """Read or hot-swap the watched contact (takes effect within seconds)."""
    config_path = BASE / 'config.json'
    if not config_path.exists():
        example = BASE / 'config.example.json'
        if not example.exists():
            print('缺少 config.json —— 请先复制 config.example.json 为 config.json。')
            return 1
        config_path.write_text(example.read_text(encoding='utf-8-sig'), encoding='utf-8')
        print('已从 config.example.json 生成 config.json。')
    config = json.loads(config_path.read_text(encoding='utf-8-sig'))
    name = (name or '').strip()
    if not name:
        print('当前监听对象：%s' % config.get('contact'))
        return 0
    config['contact'] = name
    config_path.write_text(json.dumps(config, ensure_ascii=False, indent=2), encoding='utf-8')
    print('已切换为「%s」。请在微信里打开该对话并停在底部，几秒内生效。' % name)
    return 0


def main():
    argv = sys.argv[1:]
    action = (argv[0] if argv else 'status').lower()
    if action == 'restart':
        do_stop()
        print()
        return do_start()
    if action == 'contact':
        return do_contact(argv[1] if len(argv) > 1 else '')
    table = {'status': do_status, 'start': do_start, 'stop': do_stop}
    if action not in table:
        print('用法: python listener_ctl.py [status|start|stop|restart|contact [名字]]')
        return 2
    return table[action]()


if __name__ == '__main__':
    raise SystemExit(main())
