import base64
import hashlib
import json
import os
import queue
import random
import re
import shutil
import subprocess
import threading
import time
import urllib.request
from tkinter import messagebox, ttk
import tkinter as tk

import cv2
import keyboard
import numpy as np

# =====================================================================
#                      CẤU HÌNH MẶC ĐỊNH (sửa ở đây)
# =====================================================================
DEFAULT_MODE = "correct"         # "quiz" (ngẫu nhiên) hoặc "correct" (học đáp án đúng)
DEFAULT_PRACTICE = "all"         # "all" hoặc "wrong"
DEFAULT_ROUNDS = "Loop"          # "1", "2", "3", "5", "10" hoặc "Loop"
DEFAULT_D1 = 5.0                 # giây chờ giữa chọn đáp án -> Next
DEFAULT_D2 = 3.0                 # giây chờ sau Next để câu mới load
DEFAULT_QUIZ_NAME = "default"
DEFAULT_AUTO_QUIZ_NAME = True    # tự lấy tên bài từ tên tab
USE_KEYBOARD = True              # ưu tiên phím 1-5 và phím phải; chuột chỉ là dự phòng
IGNORE_TAB_TITLES = ["teach smart", "new tab", "tab mới"]
CDP_PORT = 9222
MAX_MISS = 5
MAX_START_FAIL = 3               # bấm Luyện tất cả thất bại liên tiếp quá số này thì dừng
WINDOW_SIZE = "620x800"
# =====================================================================

BASE = os.path.dirname(os.path.abspath(__file__))
DB_FILE = "quiz_db.json"
DATA_DIR = "quiz_data"

CHROME_FLAGS = [
    f"--remote-debugging-port={CDP_PORT}",
    "--remote-allow-origins=*",
    "--disable-features=CalculateNativeWinOcclusion",
    "--disable-backgrounding-occluded-windows",
    "--disable-renderer-backgrounding",
    "--disable-background-timer-throttling",
    "--new-window",
]

CDP_KEYS = {
    "1": ("1", "Digit1", 49, "1"),
    "2": ("2", "Digit2", 50, "2"),
    "3": ("3", "Digit3", 51, "3"),
    "4": ("4", "Digit4", 52, "4"),
    "5": ("5", "Digit5", 53, "5"),
    "right": ("ArrowRight", "ArrowRight", 39, None),
}

# Trạng thái trang. Không yêu cầu phần tử nằm trong khung nhìn (UI hẹp đẩy nút xuống dưới).
# Với mỗi mẫu chữ lấy phần tử SÂU NHẤT (không chứa phần tử khớp khác), tránh nhầm khung bao ngoài.
STATE_JS = r"""
(() => {
  const vis = e => { const r = e.getBoundingClientRect(); const s = getComputedStyle(e);
    return r.width > 0 && r.height > 0 && s.visibility !== 'hidden' && s.display !== 'none'; };
  const txt = e => (e.innerText || e.value || '').replace(/\s+/g, ' ').trim();
  const els = [...document.querySelectorAll(
    'button,a,div,span,label,li,p,input[type=button],input[type=submit]')]
    .filter(e => vis(e) && txt(e).length > 0 && txt(e).length < 600);
  const leafOf = re => {
    const c = els.filter(e => re.test(txt(e)));
    const l = c.filter(e => !c.some(o => o !== e && e.contains(o)));
    return l.length ? l[0] : null;
  };
  const info = e => {
    if (!e) return null;
    const b = e.closest('button,a,[role=button]') || e;
    const r = e.getBoundingClientRect();
    const dis = b.disabled || b.getAttribute('aria-disabled') === 'true' ||
                /disabled/.test(b.className || '') || getComputedStyle(b).pointerEvents === 'none';
    return {x: r.left + r.width / 2, y: r.top + r.height / 2, t: txt(e), dis: !!dis};
  };
  const options = [];
  for (let n = 1; n <= 5; n++) {
    const e = leafOf(new RegExp('^' + n + '\\s*-'));
    if (e) options.push(Object.assign({n: n}, info(e)));
  }
  return JSON.stringify({
    next: info(leafOf(/^Tiếp$/)),
    finish: info(leafOf(/^Kết thúc luyện thi$/)),
    all: info(leafOf(/^Luyện tất cả/)),
    wrong: info(leafOf(/^Luyện câu sai/)),
    confirm: info(leafOf(/^(OK|Đồng ý|Xác nhận|Có)$/)),
    popup: /học đủ thời gian tối đa/i.test(document.body.innerText || ''),
    options: options
  });
})()
"""

# Tìm phần tử sâu nhất khớp chữ, cuộn vào giữa màn hình rồi trả về toạ độ tâm
LOCATE_JS = r"""
((src) => {
  const re = new RegExp(src);
  const vis = e => { const r = e.getBoundingClientRect(); const s = getComputedStyle(e);
    return r.width > 0 && r.height > 0 && s.visibility !== 'hidden' && s.display !== 'none'; };
  const txt = e => (e.innerText || e.value || '').replace(/\s+/g, ' ').trim();
  const c = [...document.querySelectorAll('button,a,div,span,label,li,p,input[type=button],input[type=submit]')]
    .filter(e => vis(e) && txt(e).length < 80 && re.test(txt(e)));
  const l = c.filter(e => !c.some(o => o !== e && e.contains(o)));
  if (!l.length) return null;
  const e = l[0];
  e.scrollIntoView({block: 'center'});
  const r = e.getBoundingClientRect();
  return JSON.stringify({x: r.left + r.width / 2, y: r.top + r.height / 2, t: txt(e)});
})(%s)
"""

# click() trực tiếp trên phần tử sâu nhất và các cha của nó (tối đa 3 cấp)
JS_CLICK_LEAF = r"""
((src) => {
  const re = new RegExp(src);
  const vis = e => { const r = e.getBoundingClientRect(); const s = getComputedStyle(e);
    return r.width > 0 && r.height > 0 && s.visibility !== 'hidden' && s.display !== 'none'; };
  const txt = e => (e.innerText || e.value || '').replace(/\s+/g, ' ').trim();
  const c = [...document.querySelectorAll('button,a,div,span,label,li,p,input[type=button],input[type=submit]')]
    .filter(e => vis(e) && txt(e).length < 80 && re.test(txt(e)));
  const l = c.filter(e => !c.some(o => o !== e && e.contains(o)));
  if (!l.length) return false;
  let e = l[0];
  e.scrollIntoView({block: 'center'});
  for (let i = 0; i < 4 && e; i++, e = e.parentElement) { try { e.click(); } catch (x) {} }
  return true;
})(%s)
"""

QUESTION_JS = r"""
(() => {
  const vw = innerWidth, vh = innerHeight;
  let best = null, ba = 0;
  for (const im of document.images) {
    const r = im.getBoundingClientRect();
    if (r.width < 80 || r.height < 60) continue;
    const a = r.width * r.height;
    if (a > ba) { ba = a; best = im; }
  }
  if (!best) return null;
  const r = best.getBoundingClientRect();
  let text = '';
  let el = best.parentElement;
  for (let i = 0; i < 8 && el; i++, el = el.parentElement) {
    const t = el.innerText || '';
    if (/(^|\n)\s*1\s*-/.test(t)) {
      const lines = t.split('\n').map(s => s.trim()).filter(Boolean);
      const k = lines.findIndex(s => /^1\s*-/.test(s));
      if (k > 0) {
        for (let j = k - 1; j >= 0; j--) {
          if (/Câu hỏi chọn|Góp ý/.test(lines[j])) continue;
          text = lines[j]; break;
        }
      }
      break;
    }
  }
  return JSON.stringify({src: best.currentSrc || best.src || '', text: text,
                         x: r.left + scrollX, y: r.top + scrollY, w: r.width, h: r.height});
})()
"""

ANSWER_JS = r"""
(() => { const m = (document.body.innerText || '').match(/chính xác là:\s*([1-5])\s*-/i);
         return m ? m[1] : null; })()
"""

FEEDBACK_JS = r"(() => /(Chính xác|Chưa chính xác)/.test(document.body.innerText || ''))()"

TAB_TITLE_JS = "(document.title || '').replace(/\\s+/g, ' ').trim().slice(0, 120)"
PAGE_TITLE_JS = r"""
(() => { for (const el of document.querySelectorAll('h1,h2')) {
  const t = (el.innerText || '').replace(/\s+/g, ' ').trim();
  const r = el.getBoundingClientRect();
  if (t && r.width > 0 && r.height > 0) return t.slice(0, 120); } return null; })()
"""


def path(name):
    return os.path.join(BASE, name)


def safe_dir(name):
    s = re.sub(r'[\\/:*?"<>|]+', "_", name).strip().rstrip(".")
    return s or "default"


def norm_text(t):
    return re.sub(r"\s+", " ", (t or "").strip().lower())


# ---------------- Cơ sở dữ liệu (cùng định dạng với tool cũ) ----------------
class QuizDB:
    def __init__(self):
        self.lock = threading.Lock()
        self.data = {}
        try:
            with open(path(DB_FILE), "r", encoding="utf-8") as f:
                self.data = json.load(f)
        except Exception:
            self.data = {}

    def save(self):
        tmp = path(DB_FILE) + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(self.data, f, ensure_ascii=False, indent=1)
        os.replace(tmp, path(DB_FILE))

    def names(self):
        return sorted(self.data.keys())

    def count(self, quiz):
        return len(self.data.get(quiz, {}))

    def clear(self, quiz=None):
        with self.lock:
            if quiz is None:
                self.data = {}
                shutil.rmtree(path(DATA_DIR), ignore_errors=True)
            else:
                self.data.pop(quiz, None)
                shutil.rmtree(os.path.join(BASE, DATA_DIR, safe_dir(quiz)), ignore_errors=True)
            self.save()

    def lookup(self, quiz, key):
        with self.lock:
            for e in self.data.get(quiz, {}).values():
                if e.get("key") == key:
                    return e["ans"]
        return None

    def set_answer(self, quiz, key, ans, n):
        with self.lock:
            for e in self.data.get(quiz, {}).values():
                if e.get("key") == key:
                    old = e["ans"]
                    e["ans"], e["n"] = ans, n
                    self.save()
                    return old
        return None

    def add(self, quiz, key, ans, n, crop):
        with self.lock:
            bucket = self.data.setdefault(quiz, {})
            idx = len(bucket) + 1
            fname = f"{idx:04d}.png"
            if crop is not None:
                try:
                    d = os.path.join(BASE, DATA_DIR, safe_dir(quiz))
                    os.makedirs(d, exist_ok=True)
                    cv2.imwrite(os.path.join(d, fname), crop)
                except Exception:
                    pass
            bucket[key] = {"key": key, "img": "0", "ans": ans, "n": n, "file": fname}
            self.save()
            return idx


# ---------------- Điều khiển Chrome qua CDP (không focus) ----------------
class Cdp:
    def __init__(self, ws_url):
        import websocket
        self.ws = websocket.create_connection(ws_url, timeout=15, suppress_origin=True)
        self.mid = 0
        self.lock = threading.Lock()
        for m, p in (("Page.enable", {}),
                     ("Emulation.setFocusEmulationEnabled", {"enabled": True}),
                     ("Page.setWebLifecycleState", {"state": "active"})):
            try:
                self.call(m, p)
            except Exception:
                pass

    def call(self, method, params=None):
        with self.lock:
            self.mid += 1
            mid = self.mid
            self.ws.send(json.dumps({"id": mid, "method": method, "params": params or {}}))
            while True:
                msg = json.loads(self.ws.recv())
                if msg.get("id") == mid:
                    if "error" in msg:
                        raise RuntimeError(f"{method}: {msg['error']}")
                    return msg.get("result", {})

    def close(self):
        try:
            self.ws.close()
        except Exception:
            pass

    def eval(self, js):
        r = self.call("Runtime.evaluate", {"expression": js, "returnByValue": True})
        return r.get("result", {}).get("value")

    def eval_json(self, js):
        v = self.eval(js)
        try:
            return json.loads(v) if v else None
        except Exception:
            return None

    def state(self):
        return self.eval_json(STATE_JS) or {}

    def tab_title(self):
        t = (self.eval(TAB_TITLE_JS) or "").strip()
        if not t or any(k in t.lower() for k in IGNORE_TAB_TITLES):
            return None
        return t

    def page_title(self):
        v = self.eval(PAGE_TITLE_JS)
        return v.strip() if isinstance(v, str) and v.strip() else None

    # --- bàn phím ---
    def press(self, key):
        k, code, vk, text = CDP_KEYS[key]
        down = {"type": "keyDown", "key": k, "code": code,
                "windowsVirtualKeyCode": vk, "nativeVirtualKeyCode": vk}
        if text:
            down["text"] = text
            down["unmodifiedText"] = text
        self.call("Input.dispatchKeyEvent", down)
        time.sleep(0.05)
        self.call("Input.dispatchKeyEvent", {
            "type": "keyUp", "key": k, "code": code,
            "windowsVirtualKeyCode": vk, "nativeVirtualKeyCode": vk})

    # --- chuột ---
    def click(self, x, y):
        x, y = float(x), float(y)
        self.call("Input.dispatchMouseEvent", {"type": "mouseMoved", "x": x, "y": y})
        self.call("Input.dispatchMouseEvent", {"type": "mousePressed", "x": x, "y": y,
                                               "button": "left", "buttons": 1, "clickCount": 1})
        time.sleep(0.05)
        self.call("Input.dispatchMouseEvent", {"type": "mouseReleased", "x": x, "y": y,
                                               "button": "left", "buttons": 0, "clickCount": 1})

    def locate(self, pattern):
        """Cuộn phần tử khớp chữ vào giữa màn hình, trả về {x, y, t} hoặc None."""
        res = self.eval_json(LOCATE_JS % json.dumps(pattern))
        if res:
            time.sleep(0.25)
            res = self.eval_json(LOCATE_JS % json.dumps(pattern)) or res
        return res

    def click_text(self, pattern):
        p = self.locate(pattern)
        if p:
            self.click(p["x"], p["y"])
        return p

    def deep_click(self, x, y):
        js = r"""((x,y)=>{const e=document.elementFromPoint(x,y); if(!e) return false;
          const b=e.closest('button,a,[role=button]')||e;
          for (const t of ['pointerdown','mousedown','pointerup','mouseup','click']) {
            const C = t.startsWith('pointer') ? PointerEvent : MouseEvent;
            b.dispatchEvent(new C(t,{bubbles:true,cancelable:true,view:window,clientX:x,clientY:y,button:0}));
          }
          return true;})(%s,%s)""" % (float(x), float(y))
        return bool(self.eval(js))

    def js_click(self, pattern):
        return bool(self.eval(JS_CLICK_LEAF % json.dumps(pattern)))

    def probe(self, x, y):
        js = r"""((x,y)=>{const e=document.elementFromPoint(x,y); if(!e) return null;
          return (e.tagName+'.'+(e.className||'')+' | '+(e.innerText||'').slice(0,40)).replace(/\s+/g,' ');})(%s,%s)""" % (float(x), float(y))
        return self.eval(js)

    def screenshot(self, filename):
        try:
            r = self.call("Page.captureScreenshot", {"format": "png"})
            with open(filename, "wb") as f:
                f.write(base64.b64decode(r["data"]))
        except Exception:
            pass

    def crop(self, info):
        try:
            r = self.call("Page.captureScreenshot", {
                "format": "png", "captureBeyondViewport": True, "clip": {
                    "x": max(0, info["x"]), "y": max(0, info["y"]),
                    "width": info["w"], "height": info["h"], "scale": 1}})
            arr = np.frombuffer(base64.b64decode(r["data"]), np.uint8)
            return cv2.imdecode(arr, cv2.IMREAD_COLOR)
        except Exception:
            return None


def cdp_pages():
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{CDP_PORT}/json", timeout=2) as r:
            data = json.loads(r.read().decode("utf-8"))
    except Exception:
        return []
    out = []
    for p in data:
        if p.get("type") == "page" and p.get("webSocketDebuggerUrl"):
            title = (p.get("title") or p.get("url") or "")[:70]
            out.append((f"[Chrome nền] {title}", p["webSocketDebuggerUrl"]))
    out.sort(key=lambda it: 0 if "ôn luyện" in it[0].lower() or "phần" in it[0].lower() else 1)
    return out


def find_browser():
    pf = os.environ.get("ProgramFiles", r"C:\Program Files")
    pf86 = os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)")
    la = os.environ.get("LocalAppData", "")
    for p in (pf + r"\Google\Chrome\Application\chrome.exe",
              pf86 + r"\Google\Chrome\Application\chrome.exe",
              la + r"\Google\Chrome\Application\chrome.exe",
              pf86 + r"\Microsoft\Edge\Application\msedge.exe",
              pf + r"\Microsoft\Edge\Application\msedge.exe"):
        if p and os.path.exists(p):
            return p
    return None


def profile_cmdlines():
    ps = ("Get-CimInstance Win32_Process -Filter "
          "\"Name='chrome.exe' OR Name='msedge.exe'\" | "
          "Where-Object { $_.CommandLine -like '*chrome-profile*' } | "
          "ForEach-Object { $_.CommandLine }")
    try:
        out = subprocess.run(["powershell", "-NoProfile", "-Command", ps],
                             capture_output=True, text=True, timeout=15,
                             creationflags=0x08000000).stdout
        return [ln for ln in out.splitlines() if ln.strip()]
    except Exception:
        return []


# ---------------- Giao diện ----------------
class App:
    def __init__(self, root):
        self.root = root
        root.title("Auto Quiz CDP")
        root.geometry(WINDOW_SIZE)
        self.q = queue.Queue()
        self.stop_evt = threading.Event()
        self.running = False
        self.pages = []
        self.db = QuizDB()

        pad = {"padx": 10, "pady": 4}
        frm = ttk.Frame(root)
        frm.pack(fill="both", expand=True, padx=8, pady=8)

        box = ttk.LabelFrame(frm, text="Tab Chrome (chạy ngầm, không focus)")
        box.pack(fill="x", **pad)
        row = ttk.Frame(box)
        row.pack(fill="x", padx=6, pady=4)
        self.cb_target = ttk.Combobox(row, state="readonly")
        self.cb_target.pack(side="left", fill="x", expand=True)
        ttk.Button(row, text="Làm mới", command=self.refresh).pack(side="left", padx=(6, 0))
        ttk.Button(row, text="Mở Chrome quiz", command=self.open_chrome).pack(side="left", padx=(6, 0))

        mbox = ttk.LabelFrame(frm, text="Chế độ")
        mbox.pack(fill="x", **pad)
        self.mode_var = tk.StringVar(value=DEFAULT_MODE)
        ttk.Radiobutton(mbox, text="auto-quiz (chọn ngẫu nhiên)",
                        variable=self.mode_var, value="quiz").pack(anchor="w", padx=6)
        ttk.Radiobutton(mbox, text="auto-quiz-correct (học và sửa đáp án đúng)",
                        variable=self.mode_var, value="correct").pack(anchor="w", padx=6)
        self.auto_var = tk.BooleanVar(value=DEFAULT_AUTO_QUIZ_NAME)
        ttk.Checkbutton(mbox, variable=self.auto_var,
                        text="Tự lấy tên bài từ tên tab").pack(anchor="w", padx=6)
        self.key_var = tk.BooleanVar(value=USE_KEYBOARD)
        ttk.Checkbutton(mbox, variable=self.key_var,
                        text="Ưu tiên phím 1-5 và phím phải (chuột là dự phòng)").pack(anchor="w", padx=6)
        qrow = ttk.Frame(mbox)
        qrow.pack(fill="x", padx=6, pady=2)
        ttk.Label(qrow, text="Tên bài quiz:").pack(side="left")
        names = self.db.names()
        self.quiz_var = tk.StringVar(
            value=DEFAULT_QUIZ_NAME if (DEFAULT_QUIZ_NAME in names or not names) else names[0])
        self.cb_quiz = ttk.Combobox(qrow, textvariable=self.quiz_var, width=36, values=names)
        self.cb_quiz.pack(side="left", padx=6)
        self.cb_quiz.bind("<<ComboboxSelected>>", lambda e: self.show_count())
        self.count_var = tk.StringVar()
        ttk.Label(qrow, textvariable=self.count_var, foreground="#555").pack(side="left")
        crow = ttk.Frame(mbox)
        crow.pack(fill="x", padx=6, pady=(0, 4))
        ttk.Button(crow, text="Xoá bài này", command=self.clear_one).pack(side="left")
        ttk.Button(crow, text="Xoá tất cả lịch sử", command=self.clear_all).pack(side="left", padx=6)
        self.show_count()

        qbox = ttk.LabelFrame(frm, text="Sau khi kết thúc, luyện tiếp")
        qbox.pack(fill="x", **pad)
        self.practice_var = tk.StringVar(value=DEFAULT_PRACTICE)
        ttk.Radiobutton(qbox, text="Luyện tất cả", variable=self.practice_var,
                        value="all").pack(anchor="w", padx=6)
        ttk.Radiobutton(qbox, text="Luyện câu sai (hết câu sai thì luyện tất cả)",
                        variable=self.practice_var, value="wrong").pack(anchor="w", padx=6)

        pbox = ttk.LabelFrame(frm, text="Thông số")
        pbox.pack(fill="x", **pad)
        g = ttk.Frame(pbox)
        g.pack(fill="x", padx=6, pady=4)
        ttk.Label(g, text="Số lượt làm (1 / 2 / số khác / Loop):").grid(row=0, column=0, sticky="w")
        self.rounds_var = tk.StringVar(value=DEFAULT_ROUNDS)
        ttk.Combobox(g, textvariable=self.rounds_var, width=8,
                     values=["1", "2", "3", "5", "10", "Loop"]).grid(row=0, column=1, padx=6, pady=2)
        ttk.Label(g, text="Chờ giữa chọn đáp án → Next (giây):").grid(row=1, column=0, sticky="w")
        self.d1_var = tk.StringVar(value=str(DEFAULT_D1))
        ttk.Spinbox(g, from_=0.2, to=30, increment=0.5, width=8,
                    textvariable=self.d1_var).grid(row=1, column=1, padx=6, pady=2)
        ttk.Label(g, text="Chờ sau Next để câu mới load (giây):").grid(row=2, column=0, sticky="w")
        self.d2_var = tk.StringVar(value=str(DEFAULT_D2))
        ttk.Spinbox(g, from_=0.2, to=10, increment=0.2, width=8,
                    textvariable=self.d2_var).grid(row=2, column=1, padx=6, pady=2)

        bbox = ttk.Frame(frm)
        bbox.pack(fill="x", **pad)
        self.btn_start = ttk.Button(bbox, text="Start (F8)", command=self.start)
        self.btn_start.pack(side="left", fill="x", expand=True, padx=(0, 4))
        self.btn_stop = ttk.Button(bbox, text="Stop (Esc)", command=self.stop, state="disabled")
        self.btn_stop.pack(side="left", fill="x", expand=True, padx=4)
        ttk.Button(bbox, text="Test", command=self.test).pack(side="left", padx=(4, 0))

        self.status = tk.StringVar(value="Sẵn sàng")
        ttk.Label(frm, textvariable=self.status, font=("Segoe UI", 10, "bold")).pack(anchor="w", **pad)
        self.counter = tk.StringVar(value="Lượt: 0 | Câu trong lượt: 0 | Tổng câu: 0")
        ttk.Label(frm, textvariable=self.counter, font=("Segoe UI", 10),
                  foreground="#0a5").pack(anchor="w", padx=10)
        self.log = tk.Text(frm, height=14, state="disabled", wrap="word")
        self.log.pack(fill="both", expand=True, **pad)

        self.refresh()
        keyboard.add_hotkey("f8", lambda: root.after(0, self.toggle))
        keyboard.add_hotkey("esc", lambda: root.after(0, self.stop))
        root.protocol("WM_DELETE_WINDOW", self.close)
        self.poll()

    # --- tiện ích UI ---
    def show_count(self):
        self.count_var.set(f"({self.db.count(self.quiz_var.get().strip())} câu đã học)")

    def reload_quiz_list(self):
        self.cb_quiz["values"] = self.db.names()
        self.show_count()

    def clear_one(self):
        if self.running:
            return self.put("Hãy dừng tool trước khi xoá")
        quiz = self.quiz_var.get().strip()
        if quiz and messagebox.askyesno("Xoá", f"Xoá dữ liệu bài '{quiz}'?"):
            self.db.clear(quiz)
            self.reload_quiz_list()
            self.put(f"Đã xoá bài '{quiz}'")

    def clear_all(self):
        if self.running:
            return self.put("Hãy dừng tool trước khi xoá")
        if messagebox.askyesno("Xoá", "Xoá TOÀN BỘ lịch sử?"):
            self.db.clear(None)
            self.reload_quiz_list()
            self.put("Đã xoá toàn bộ lịch sử")

    def refresh(self):
        self.pages = cdp_pages()
        self.cb_target["values"] = [p[0] for p in self.pages]
        if self.pages:
            self.cb_target.current(0)
        else:
            self.cb_target.set("")

    def open_chrome(self):
        threading.Thread(target=self._open_chrome, daemon=True).start()

    def _open_chrome(self):
        exe = find_browser()
        if not exe:
            return self.put("Không tìm thấy Chrome/Edge")
        running = profile_cmdlines()
        if running and not any(f"remote-debugging-port={CDP_PORT}" in c for c in running):
            self.put("CẢNH BÁO: Chrome của profile này đang chạy KHÔNG có cổng debug.")
            self.put("-> Đóng hết Chrome quiz (kể cả trong khay hệ thống) rồi bấm lại.")
            return
        if running:
            self.put("Chrome quiz đã chạy đúng cờ, bấm Làm mới để chọn tab")
            self.root.after(0, self.refresh)
            return
        subprocess.Popen([exe, f"--user-data-dir={os.path.join(BASE, 'chrome-profile')}"]
                         + CHROME_FLAGS)
        self.put("Đã mở Chrome quiz, đăng nhập và vào trang bài tập")
        time.sleep(4)
        self.root.after(0, self.refresh)

    def put(self, msg):
        self.q.put(("log", f"{time.strftime('%H:%M:%S')}  {msg}"))

    def set_counter(self, rounds_done, rounds_total, in_round, total):
        tot = "∞" if rounds_total is None else str(rounds_total)
        self.q.put(("count", f"Lượt: {rounds_done}/{tot} | Câu trong lượt: {in_round} | "
                             f"Tổng câu: {total}"))

    def poll(self):
        try:
            while True:
                kind, val = self.q.get_nowait()
                if kind == "log":
                    self.log.config(state="normal")
                    self.log.insert("end", val + "\n")
                    self.log.see("end")
                    self.log.config(state="disabled")
                elif kind == "status":
                    self.status.set(val)
                elif kind == "count":
                    self.counter.set(val)
                elif kind == "quiz":
                    self.quiz_var.set(val)
                    self.reload_quiz_list()
                elif kind == "done":
                    self.running = False
                    self.btn_start.config(state="normal")
                    self.btn_stop.config(state="disabled")
                    self.status.set("Đã dừng")
                    self.reload_quiz_list()
        except queue.Empty:
            pass
        self.root.after(100, self.poll)

    def close(self):
        self.stop_evt.set()
        keyboard.unhook_all()
        self.root.destroy()

    def toggle(self):
        if self.running:
            self.stop()
        else:
            self.start()

    def stop(self):
        if self.running:
            self.stop_evt.set()
            self.status.set("Đang dừng...")

    def connect(self):
        i = self.cb_target.current()
        if i < 0 or i >= len(self.pages):
            self.put("Chưa có tab [Chrome nền]. Bấm 'Mở Chrome quiz' rồi 'Làm mới'")
            return None
        try:
            return Cdp(self.pages[i][1])
        except Exception as e:
            self.put(f"Không kết nối được: {e!r}")
            return None

    def test(self):
        c = self.connect()
        if c:
            threading.Thread(target=self._test, args=(c,), daemon=True).start()

    def _test(self, c):
        try:
            fv = c.eval('document.hasFocus() + " / " + document.visibilityState')
            self.put(f"Focus/visibility: {fv}")
            self.put(f"Tên tab: {c.tab_title()!r} | h1/h2: {c.page_title()!r}")
            st = c.state()
            for k in ("next", "finish", "all", "wrong", "confirm"):
                v = st.get(k)
                extra = ""
                if v:
                    extra = f" tại ({int(v['x'])},{int(v['y'])}) '{v['t']}'"
                    extra += " (bị khoá)" if v.get("dis") else ""
                self.put(f"  {k}: {'có' if v else 'không'}{extra}")
            self.put(f"  popup hết giờ: {'CÓ' if st.get('popup') else 'không'}")
            self.put(f"  Đáp án tìm thấy: {[o['n'] for o in st.get('options', [])]}")
            info = c.eval_json(QUESTION_JS)
            self.put(f"  Ảnh câu hỏi: {'...' + info['src'][-50:] if info else 'không có'}")
            if info:
                self.put(f"  Dòng câu hỏi: {info['text'][:70]}")
        except Exception as e:
            self.put(f"Lỗi test: {e!r}")
        finally:
            c.close()

    def start(self):
        if self.running:
            return
        quiz = self.quiz_var.get().strip() or DEFAULT_QUIZ_NAME
        c = self.connect()
        if not c:
            return
        txt = self.rounds_var.get().strip().lower()
        if txt == "loop":
            rounds = None
        else:
            try:
                rounds = max(1, int(txt))
            except ValueError:
                rounds = 1
        try:
            d1 = float(self.d1_var.get().replace(",", "."))
            d2 = float(self.d2_var.get().replace(",", "."))
        except ValueError:
            d1, d2 = DEFAULT_D1, DEFAULT_D2
        self.stop_evt.clear()
        self.running = True
        self.btn_start.config(state="disabled")
        self.btn_stop.config(state="normal")
        self.status.set("Đang chạy...")
        self.set_counter(0, rounds, 0, 0)
        threading.Thread(target=self.worker, daemon=True, args=(
            c, rounds, d1, d2, self.practice_var.get(), self.mode_var.get(),
            quiz, self.auto_var.get(), self.key_var.get())).start()

    # --- luồng chạy ---
    def nap(self, t):
        return self.stop_evt.wait(t)

    def worker(self, c, *args):
        try:
            self.run(c, *args)
        except Exception as e:
            self.put(f"LỖI: {e!r}")
        finally:
            c.close()
            self.put("Kết thúc")
            self.q.put(("done", None))

    def wait_state(self, c, cond, timeout):
        t0 = time.time()
        while time.time() - t0 < timeout and not self.stop_evt.is_set():
            st = c.state()
            if cond(st) or st.get("popup"):
                return st
            self.nap(0.5)
        return None

    @staticmethod
    def is_question(st):
        return bool(st.get("options"))

    @staticmethod
    def is_summary(st):
        return not st.get("options") and bool(st.get("all") or st.get("wrong"))

    @staticmethod
    def sig(st):
        return "|".join(o["t"] for o in st.get("options", []))

    def read_right(self, c):
        prev = None
        for _ in range(10):
            if self.nap(0.5):
                return None
            v = c.eval(ANSWER_JS)
            cur = int(v) if v else None
            if cur is not None and cur == prev:
                return cur
            prev = cur
        return prev

    def choose(self, c, choice, use_keys):
        """Chọn đáp án: phím trước, kiểm tra trang đã phản hồi, không được thì click chuột."""
        if use_keys:
            c.press(str(choice))
            for _ in range(6):
                self.nap(0.4)
                if c.eval(FEEDBACK_JS):
                    return "phím"
            self.put("  Phím số không có phản hồi -> thử click chuột")
        p = c.click_text(rf"^{choice}\s*-")
        if p:
            for _ in range(4):
                self.nap(0.4)
                if c.eval(FEEDBACK_JS):
                    return "chuột"
            self.put("  Click chuột chọn đáp án cũng không có phản hồi")
        return None

    def go_next(self, c, st, sig_before, use_keys, d2):
        """Sang câu tiếp: phím phải trước, không đổi thì click nút Tiếp. Trả về True nếu đã sang."""
        def moved():
            for _ in range(4):
                s2 = c.state()
                if self.sig(s2) != sig_before or self.is_summary(s2):
                    return True
                self.nap(0.6)
            return False

        if use_keys:
            c.press("right")
            if self.nap(d2):
                return False
            if moved():
                return True
            self.put("  Phím phải không sang được câu -> thử click nút Tiếp")
        if c.click_text(r"^Tiếp$"):
            if self.nap(d2):
                return False
            if moved():
                return True
        return False

    def press_start(self, c, label, key, wait):
        """Bấm nút bắt đầu lượt, thử lần lượt 3 cách và ghi log từng cách."""
        pat = "^" + re.escape(label)
        attempts = [
            ("click toạ độ (đã cuộn nút vào giữa)", lambda: c.click_text(pat)),
            ("chuỗi sự kiện chuột đầy đủ", lambda: self._deep(c, pat)),
            ("click() trực tiếp trên nút và các cha", lambda: c.js_click(pat)),
        ]
        for name, fn in attempts:
            try:
                fn()
            except Exception as e:
                self.put(f"  {name} lỗi: {e!r}")
                continue
            r = self.wait_state(c, self.is_question, wait)
            if r and (self.is_question(r) or r.get("popup")):
                self.put(f"  Thành công bằng: {name}")
                return True
            self.put(f"  {name}: không có tác dụng")
        return False

    def _deep(self, c, pat):
        p = c.locate(pat)
        if p:
            self.put(f"  tại ({int(p['x'])},{int(p['y'])}) đang là: {c.probe(p['x'], p['y'])}")
            return c.deep_click(p["x"], p["y"])
        return False

    def start_round(self, c, st, practice):
        if practice == "wrong" and st.get("wrong"):
            self.put("Bấm Luyện câu sai")
            if self.press_start(c, "Luyện câu sai", "wrong", 5):
                return True
            self.put("Không còn câu sai -> Luyện tất cả")
            st = c.state()
        if st.get("all"):
            self.put("Bấm Luyện tất cả")
            return self.press_start(c, "Luyện tất cả", "all", 8)
        self.put("Không thấy nút Luyện tất cả")
        return False

    def finish_popup(self, c, st):
        self.put("Popup: đã học đủ thời gian tối đa -> bấm OK và dừng")
        if not c.click_text(r"^OK$"):
            c.js_click(r"^OK$")

    def do_finish(self, c):
        for attempt in range(3):
            if self.stop_evt.is_set():
                return False
            if not c.click_text(r"^Kết thúc luyện thi$"):
                c.js_click(r"^Kết thúc luyện thi$")
            t0 = time.time()
            while time.time() - t0 < 8 and not self.stop_evt.is_set():
                self.nap(0.7)
                s = c.state()
                if self.is_summary(s):
                    return True
                if s.get("confirm") and not s.get("options"):
                    self.put("Bấm xác nhận")
                    if not c.click_text(r"^(OK|Đồng ý|Xác nhận|Có)$"):
                        c.js_click(r"^(OK|Đồng ý|Xác nhận|Có)$")
            self.put(f"Chưa sang màn tổng kết, thử lại ({attempt + 2}/3)")
        return False

    def run(self, c, rounds, d1, d2, practice, mode, quiz, auto, use_keys):
        self.put("Chế độ CDP thuần: không focus, không dùng chuột/bàn phím thật"
                 f"{' | ưu tiên phím' if use_keys else ''}")
        cur_quiz = quiz
        rounds_done = total = in_round = miss = start_fail = 0

        while not self.stop_evt.is_set():
            st = c.state()

            if st.get("popup"):
                self.finish_popup(c, st)
                break

            if self.is_summary(st):
                if rounds is not None and rounds_done >= rounds:
                    self.put(f"Đã hoàn thành {rounds_done} lượt")
                    break
                self.put(f"Bắt đầu lượt {rounds_done + 1}"
                         f"{'' if rounds is None else '/' + str(rounds)}")
                if self.start_round(c, st, practice):
                    start_fail = 0
                    in_round = 0
                    self.set_counter(rounds_done, rounds, in_round, total)
                else:
                    start_fail += 1
                    if start_fail >= MAX_START_FAIL:
                        self.put(f"Bấm bắt đầu lượt thất bại {start_fail} lần liên tiếp -> dừng")
                        c.screenshot(path("debug.png"))
                        self.put("Đã lưu debug.png (ảnh trang lúc đó)")
                        break
                    self.nap(1.5)
                continue

            if not self.is_question(st):
                miss += 1
                self.put(f"Không nhận diện được màn hình ({miss}/{MAX_MISS})")
                if miss >= MAX_MISS:
                    c.screenshot(path("debug.png"))
                    break
                self.nap(1.5)
                continue
            miss = 0

            if auto:
                nm = c.tab_title() or c.page_title()
                if nm and nm != cur_quiz:
                    cur_quiz = nm
                    self.put(f"Bài quiz hiện tại: '{cur_quiz}' ({self.db.count(cur_quiz)} câu đã học)")
                    self.q.put(("quiz", cur_quiz))

            opts = st["options"]
            n = len(opts)
            sig_before = self.sig(st)
            info = c.eval_json(QUESTION_JS)
            key = None
            if info and info.get("src"):
                src = info["src"]
                if not src.startswith("data:"):
                    src = src.split("?")[0].split("#")[0]
                key = hashlib.sha1((src + "|" + norm_text(info.get("text"))).encode()).hexdigest()[:16]

            known = self.db.lookup(cur_quiz, key) if (mode == "correct" and key) else None
            if known is not None and 1 <= known <= n:
                choice, tag = known, "đã biết"
            else:
                choice, known = random.randint(1, n), None
                tag = "chưa biết" if mode == "correct" else "ngẫu nhiên"

            how = self.choose(c, choice, use_keys)
            if how is None:
                self.put("Không chọn được đáp án -> thử lại câu này")
                c.screenshot(path("debug.png"))
                miss += 1
                if miss >= MAX_MISS:
                    break
                self.nap(1.5)
                continue

            if mode == "correct" and key:
                right = self.read_right(c)
                if right is None:
                    self.put("Không đọc được 'Câu trả lời chính xác là' -> bỏ qua việc học câu này")
                elif known is None:
                    idx = self.db.add(cur_quiz, key, right, n, c.crop(info) if info else None)
                    self.put(f"Đã học câu #{idx} của '{cur_quiz}': đáp án đúng là {right}")
                elif right != choice:
                    old = self.db.set_answer(cur_quiz, key, right, n)
                    self.put(f"CẬP NHẬT: đáp án đã lưu ({old}) sai, đáp án đúng là {right}")
                    tag = f"sai -> sửa thành {right}"

            if self.nap(d1):
                break

            st = c.state()
            nx = st.get("next")
            has_next = bool(nx) and not nx.get("dis")
            in_round += 1
            total += 1
            self.set_counter(rounds_done, rounds, in_round, total)
            self.q.put(("status", f"Đang chạy - lượt {rounds_done + 1}"))
            self.put(f"Câu {in_round} (tổng {total}): chọn {choice}/{n} ({tag}, bằng {how})")

            if has_next:
                if self.go_next(c, st, sig_before, use_keys, d2):
                    continue
                self.put("Không sang được câu tiếp -> Kết thúc luyện thi")
            else:
                self.put("Câu cuối -> Kết thúc luyện thi")

            if self.do_finish(c):
                rounds_done += 1
                self.set_counter(rounds_done, rounds, in_round, total)
                self.put(f"=== Xong lượt {rounds_done} ===")
            else:
                self.put("Không sang được màn tổng kết")
                c.screenshot(path("debug.png"))
                break


if __name__ == "__main__":
    root = tk.Tk()
    App(root)
    root.mainloop()