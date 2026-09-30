# wechat-gui-autoreply

**A read-only WeChat observer that turns incoming messages into reply *drafts* — by driving the
desktop UI, not the network.**

WeChat does not offer an official personal-account messaging API. Every "auto-reply bot" you see
either gets accounts banned for using reverse-engineered protocols, or quietly dies when the client
updates. This project takes a third route:

> If a human can read the chat window, a program can read the chat window too.
> Use UI Automation to *observe*, and hand the thinking to whatever agent/LLM you already run.

The observer **never clicks, never types, never sends**. It watches one conversation, detects a new
incoming message, writes a request file, waits for a reply file, and saves the result as a
markdown draft. Delivery stays manual, by design.

---

## 1. What it actually does

```
        WeChat desktop window (must be foreground, scrolled to the bottom)
                 │
                 │  UI Automation: read the message list only
                 ▼
        ┌──────────────────┐
        │    listener.py   │   poll every 2s
        │  ─ Tracker       │   diff by message id → only true appends count
        │  ─ Reader        │   sender determined by avatar template matching
        └────────┬─────────┘
                 │  writes bridge/request.json   {request_id, contact, context, prompt}
                 ▼
        ┌──────────────────────────────┐
        │   YOUR agent / LLM runtime   │   anything that can read a file and write one back
        └──────────────┬───────────────┘
                       │  writes bridge/response.json  {request_id, reply:{...}}
                       ▼
                 latest-draft.md          ← the deliverable. You read it, you decide.
```

Nothing is sent. The output is a draft.

---

## 2. Files

| File | Role |
|---|---|
| `listener.py` | The observer. Read-only UIA loop + `EventBridge` file mailbox. |
| `listener_ctl.py` | Start / stop / status / contact switch. Stdlib only. |
| `listener_*.bat` | Double-click wrappers for the three actions above. |
| `bridge_cli.py` | Host-agent side CLI: `wait` / `check` / `respond`. Zero-token blocking wait. |
| `session_view.py` | Renders a pending `request.json` into a human-readable transcript. |
| `schema.json` | The reply contract (`reply_text`, `sticker_suggestion`). |
| `config.example.json` | Copy to `config.json` and edit. |
| `style.example.md` | Copy to `style.md` and edit — this is the prompt preamble. |
| `test_listener.py` | Unit tests for the tracking logic. |
| `e2e_synthetic_test.py` | End-to-end test of the event protocol with a synthetic reply. |

---

## 3. Requirements

- **Windows 10/11** (UI Automation + WeChat desktop client)
- **WeChat for Windows**, already logged in, Chinese UI
- Python 3.10+
- The WeChat window must be **foreground** and **scrolled to the bottom of the target chat**

```bash
python -m pip install -r requirements.txt
```

---

## 4. Quickstart

```bash
git clone https://github.com/<you>/wechat-gui-autoreply.git
cd wechat-gui-autoreply

python -m pip install -r requirements.txt

copy config.example.json config.json     # then edit: set "contact" to the exact WeChat display name
copy style.example.md  style.md          # then edit: write your own drafting rules
```

Open WeChat, open that conversation, leave it scrolled at the bottom, then:

```bash
python listener_ctl.py status     # expect: 状态：未运行  [OFF]
python listener_ctl.py start      # expect: 已启动，PID xxxxx
python listener_ctl.py status     # expect: 状态：监听中  [ON]
```

Send yourself a message from another account (or a friend) and watch `latest-draft.md` appear.

Stop with:

```bash
python listener_ctl.py stop
```

Or just double-click `listener-start.bat` / `listener-status.bat` / `listener-stop.bat`.

---

## 5. Is it running? How do I stop it?

This was a real pain point, so the status check uses **two independent pieces of evidence** — a
fresh heartbeat *and* a live PID. Either one alone lies:

- the heartbeat file outlives a crashed process
- a recycled PID can look alive
- after a hard kill the heartbeat freezes, which looks identical to "healthy but idle"

```bash
python listener_ctl.py status
```

| Output | Meaning |
|---|---|
| `状态：监听中  [ON]` + PID / 心跳 / 联系人 / revision | healthy |
| `状态：未运行  [OFF]` + 原因 | not running, and *why* |

`stop` first drops a `state/stop` sentinel file (graceful), waits up to 10s, then force-terminates.
`start` is idempotent — running it twice does not spawn a second instance.

Switching the watched contact without restarting:

```bash
python listener_ctl.py contact          # show current target
python listener_ctl.py contact 张三      # hot-swap
```

> Note: `pid_alive()` uses ctypes `OpenProcess` + `GetExitCodeProcess`.
> **Never** use `os.kill(pid, 0)` on Windows — it does not mean "probe", it means *terminate*.

---

## 6. The bridge protocol

`bridge/request.json`:

```json
{
  "protocol": 1,
  "request_id": "9f2c...",
  "status": "pending",
  "created_at": 1759200000.0,
  "contact": "ExampleContact",
  "revision": 12,
  "context": [{"id": "...", "sender": "peer", "text": "在吗", "kind": "text"}],
  "prompt": "...",
  "mode": "draft_only"
}
```

`bridge/response.json`:

```json
{
  "request_id": "9f2c...",
  "reply": {"reply_text": "在的，怎么了？", "sticker_suggestion": "none"}
}
```

Rules the implementation enforces:

- `request_id` **must** match, or the response is ignored.
- `reply` **must** contain exactly `reply_text` and `sticker_suggestion`, both strings.
- A request is invalidated (→ `status: "cancelled"`) whenever the conversation moves on. A draft
  answering a stale message is worse than no draft.
- On restart, any leftover `pending` request is re-marked `cancelled / listener_restarted`.

Host agents should use `bridge_cli.py`:

```bash
python bridge_cli.py wait --timeout 300      # block locally until a fresh request lands
python bridge_cli.py check  --request-id 9f2c...
python bridge_cli.py respond --request-id 9f2c... --reply-file reply.json
```

`wait` is **pure local file polling** — it burns zero model tokens. Do not implement event detection
by repeatedly calling an LLM.

---

## 7. How the hard parts are solved

**Detecting a new message without reading the whole history.**
Each row gets an id of `contact|runtimeId|text`. The tracker keeps the previous id sequence and only
accepts elements *appended after the former tail*. If the old tail is gone (user scrolled, history
loaded), it re-baselines instead of guessing. This makes scrolls and virtualized-list churn
harmless.

**Telling "them" from "me".**
There is no reliable sender field in the UIA tree. So: crop the left 36×36 avatar lane and the right
one, compare each against a template over a ±2px offset search, and take the minimum mean absolute
difference. Below 18 → match. Templates are **self-calibrated**: a lane is only learned when it is
textured *and* the opposite lane is empty, so a single lone bubble cannot poison both templates.

**Not answering half a sentence.**
A new message only arms the pipeline after the chat has been still for 3 seconds, and generation is
preceded by one more fresh read. People send "在吗" then "帮我看个事" two seconds later; you want the
second one included.

**Knowing the chat is actually at the bottom.**
Three checks: a "N new messages" divider in the lower half, the scrollbar thumb not at the bottom,
or the last bubble not flush with the pane bottom. Any one of them → pause and report why. The
scrollbar is nearly invisible in Qt, so the thumb test is a low-saturation/ranged-gray pixel count
rather than a color match.

**Reading only the target window.**
Root-level UIA enumeration can hang on unrelated providers. The reader resolves the foreground HWND
once and searches downward from it. If the foreground window or the chat title changes mid-read, the
whole read is discarded.

---

## 8. Limitations (read these)

- **Foreground only.** WeChat must be the active window on the target conversation, scrolled to the
  bottom. Reading a background window was not implemented because it could not be validated without
  disturbing a live session.
- **No backfill.** Messages arriving while the listener is paused/stopped are not replayed. The
  tracker re-baselines and waits for the *next* message.
- **Sending is not implemented.** Not a missing feature — the whole point. Draft-only.
- **LLM hallucination is real.** Style prompts say "never invent past facts"; models still do it.
  Read the draft before sending. Always.
- **Heartbeat frequency ≠ liveness.** It reflects the process, not whether WeChat is cooperating.
- **UI Automation breaks on WeChat updates.** The long automation-id strings in `listener.py`
  (`chat_message_list`, `chat_bubble_item_view`, …) are version-specific. Verify with
  `python listener.py --probe` after any client update.

---

## 9. Legal / ethical

This is a personal-assistant tool. Before you run it:

- Automating a personal WeChat account is **against the service terms**, for any client-side
  approach. Only you can decide whether that matters for your use.
- It reads **one** conversation you configure, and only while it is on screen and focused. It does
  not enumerate contacts, export history, or touch anything you did not point it at.
- Do not use this for bulk messaging, marketing, or anything where the recipient does not know a
  machine wrote it. It is built for "my hands are busy, draft me a reply" — not for pretending to be
  someone.
- The authors are not responsible for account restrictions resulting from its use.

---

## 10. License

MIT — see `LICENSE`.
