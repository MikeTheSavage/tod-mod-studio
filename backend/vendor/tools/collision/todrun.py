"""todrun.py - launch, drive, capture and close the PRIVATE test copy of Total Overdose.

Rules built in:
  * launches only the private test copy's TOD.exe (env TOD_TEST_GAME), and only when no TOD.exe / TotalOverdose.exe runs
  * env USERPROFILE -> lab profile, so SHGetFolderPathA(CSIDL_PERSONAL) gives the lab copy of the saves
  * keys/mouse go in only while OUR game window is foreground (checked before each event)
  * close/kill only the PID this tool started (state file run_state.json)
  * DPI-aware capture (SetProcessDpiAwarenessContext) of the game window's client area

usage:
  python todrun.py launch [--no-wait]
  python todrun.py status
  python todrun.py shot OUT.png [--scale 0.5]
  python todrun.py keys "ENTER,wait:1.5,DOWN,ENTER"        (names: see SC table; wait:<s>)
  python todrun.py hold W 6 --cap DIR --fps 25 --scale 0.5 [--also LSHIFT] [--mouse dx]
  python todrun.py close
  python todrun.py checksaves
"""
import ctypes, ctypes.wintypes as W, json, os, subprocess, sys, time, hashlib

HERE = os.path.dirname(os.path.abspath(__file__))
LAB = os.environ.get("TOD_COLL_LAB", os.path.join(HERE, "lab"))   # lab state (saves profile, log)
GAME = os.environ.get("TOD_TEST_GAME", "")   # the private test copy of the game (never the real install)
PROFILE = os.path.join(LAB, "saveiso", "profile")
STATE = os.path.join(LAB, "run_state.json")
USER_SAVES = os.path.join(os.path.expanduser("~"), "Documents", "Total Overdose", "savegames")
SAVE_LIST = os.path.join(LAB, "saveiso", "backup", "user_saves.sha256")
LOG = os.path.join(LAB, "ACTION_LOG.md")

user32 = ctypes.WinDLL("user32", use_last_error=True)
gdi32 = ctypes.WinDLL("gdi32")
kernel32 = ctypes.WinDLL("kernel32")
try:
    user32.SetProcessDpiAwarenessContext(ctypes.c_void_p(-4))
except Exception:
    user32.SetProcessDPIAware()


def log(msg):
    with open(LOG, "a", encoding="utf-8") as f:
        f.write("- %s todrun: %s\n" % (time.strftime("%Y-%m-%d %H:%M:%S"), msg))


def tod_procs():
    out = subprocess.run(["tasklist", "/FO", "CSV", "/NH"], capture_output=True, text=True).stdout
    res = []
    for line in out.splitlines():
        p = [x.strip('"') for x in line.split('","')]
        if len(p) > 1 and p[0].lower() in ("tod.exe", "totaloverdose.exe"):
            res.append((p[0], int(p[1])))
    return res


def state():
    try:
        return json.load(open(STATE))
    except Exception:
        return {}


def windows_of(pid):
    res = []
    @ctypes.WINFUNCTYPE(W.BOOL, W.HWND, W.LPARAM)
    def cb(h, l):
        p = W.DWORD()
        user32.GetWindowThreadProcessId(h, ctypes.byref(p))
        if p.value == pid and user32.IsWindowVisible(h):
            r = W.RECT(); user32.GetClientRect(h, ctypes.byref(r))
            res.append((h, r.right - r.left, r.bottom - r.top))
        return True
    user32.EnumWindows(cb, 0)
    res.sort(key=lambda x: -x[1] * x[2])
    return res


def game_hwnd():
    st = state()
    pid = st.get("pid")
    if not pid:
        return None, None
    ws = windows_of(pid)
    return (ws[0][0] if ws else None), pid


def ensure_foreground(h):
    if user32.GetForegroundWindow() == h:
        return True
    # standard trick: a synthetic ALT press lets SetForegroundWindow succeed
    user32.keybd_event(0x12, 0, 0, 0); user32.keybd_event(0x12, 0, 2, 0)
    user32.ShowWindow(h, 9)
    user32.SetForegroundWindow(h)
    time.sleep(0.3)
    return user32.GetForegroundWindow() == h


# ---- SendInput --------------------------------------------------------------------------
class KEYBDINPUT(ctypes.Structure):
    _fields_ = [("wVk", W.WORD), ("wScan", W.WORD), ("dwFlags", W.DWORD), ("time", W.DWORD), ("dwExtraInfo", ctypes.c_size_t)]
class MOUSEINPUT(ctypes.Structure):
    _fields_ = [("dx", W.LONG), ("dy", W.LONG), ("mouseData", W.DWORD), ("dwFlags", W.DWORD), ("time", W.DWORD), ("dwExtraInfo", ctypes.c_size_t)]
class _U(ctypes.Union):
    _fields_ = [("ki", KEYBDINPUT), ("mi", MOUSEINPUT), ("pad", ctypes.c_byte * 32)]
class INPUT(ctypes.Structure):
    _fields_ = [("type", W.DWORD), ("u", _U)]

SC = {"ESC": 0x01, "ENTER": 0x1C, "SPACE": 0x39, "LSHIFT": 0x2A, "LCTRL": 0x1D, "TAB": 0x0F, "BACK": 0x0E,
      "UP": 0xE048, "DOWN": 0xE050, "LEFT": 0xE04B, "RIGHT": 0xE04D, "F1": 0x3B, "F2": 0x3C,
      "W": 0x11, "A": 0x1E, "S": 0x1F, "D": 0x20, "E": 0x12, "Q": 0x10, "R": 0x13, "F": 0x21, "C": 0x2E, "X": 0x2D,
      "Y": 0x15, "N": 0x31, "1": 0x02, "2": 0x03}


def key_event(name, up):
    sc = SC[name.upper()]
    flags = 0x0008 | (0x0002 if up else 0)          # KEYEVENTF_SCANCODE | KEYUP
    if sc > 0xFF:
        flags |= 0x0001; sc &= 0xFF                 # EXTENDEDKEY
    i = INPUT(type=1); i.u.ki = KEYBDINPUT(0, sc, flags, 0, 0)
    user32.SendInput(1, ctypes.byref(i), ctypes.sizeof(INPUT))


def mouse_move(dx, dy=0):
    i = INPUT(type=0); i.u.mi = MOUSEINPUT(dx, dy, 0, 0x0001, 0, 0)
    user32.SendInput(1, ctypes.byref(i), ctypes.sizeof(INPUT))


def mouse_click(left=True):
    for fl in ((0x2, 0x4) if left else (0x8, 0x10)):
        i = INPUT(type=0); i.u.mi = MOUSEINPUT(0, 0, 0, fl, 0, 0)
        user32.SendInput(1, ctypes.byref(i), ctypes.sizeof(INPUT)); time.sleep(0.05)


def need_fg():
    h, pid = game_hwnd()
    if not h:
        sys.exit("no game window of our run")
    if not ensure_foreground(h):
        sys.exit("game window is not foreground; refusing to send input")
    return h


def press(name, dur=0.08):
    h = need_fg()
    key_event(name, False); time.sleep(dur); key_event(name, True)


# ---- capture ----------------------------------------------------------------------------
class BITMAPINFOHEADER(ctypes.Structure):
    _fields_ = [("biSize", W.DWORD), ("biWidth", W.LONG), ("biHeight", W.LONG), ("biPlanes", W.WORD), ("biBitCount", W.WORD),
                ("biCompression", W.DWORD), ("biSizeImage", W.DWORD), ("biXPelsPerMeter", W.LONG), ("biYPelsPerMeter", W.LONG),
                ("biClrUsed", W.DWORD), ("biClrImportant", W.DWORD)]


class Grabber:
    def __init__(self, h):
        r = W.RECT(); user32.GetClientRect(h, ctypes.byref(r))
        pt = W.POINT(0, 0); user32.ClientToScreen(h, ctypes.byref(pt))
        self.x, self.y, self.w, self.h = pt.x, pt.y, r.right, r.bottom
        self.sdc = user32.GetDC(0)
        self.mdc = gdi32.CreateCompatibleDC(self.sdc)
        self.bmp = gdi32.CreateCompatibleBitmap(self.sdc, self.w, self.h)
        gdi32.SelectObject(self.mdc, self.bmp)
        self.bi = BITMAPINFOHEADER(ctypes.sizeof(BITMAPINFOHEADER), self.w, -self.h, 1, 32, 0, 0, 0, 0, 0, 0)
        self.buf = ctypes.create_string_buffer(self.w * self.h * 4)

    def grab(self):
        gdi32.BitBlt(self.mdc, 0, 0, self.w, self.h, self.sdc, self.x, self.y, 0x00CC0020)
        gdi32.GetDIBits(self.mdc, self.bmp, 0, self.h, self.buf, ctypes.byref(self.bi), 0)
        return bytes(self.buf)

    def to_image(self, raw, scale=1.0):
        from PIL import Image
        im = Image.frombuffer("RGBA", (self.w, self.h), raw, "raw", "BGRA", 0, 1).convert("RGB")
        if scale != 1.0:
            im = im.resize((int(self.w * scale), int(self.h * scale)), Image.BILINEAR)
        return im

    def close(self):
        gdi32.DeleteObject(self.bmp); gdi32.DeleteDC(self.mdc); user32.ReleaseDC(0, self.sdc)


def cmd_shot(out, scale=1.0):
    h, pid = game_hwnd()
    if not h:
        sys.exit("no game window")
    g = Grabber(h)
    im = g.to_image(g.grab(), scale)
    g.close()
    im.save(out)
    print("saved", out, im.size, "client", g.w, g.h)


def cmd_launch(wait=True):
    if not GAME:
        sys.exit("REFUSED: set TOD_TEST_GAME to the private test copy of the game")
    running = tod_procs()
    if running:
        sys.exit("REFUSED: TOD already running: %r" % running)
    try:
        import shutil
        free = shutil.disk_usage("C:\\").free / 2**30
        if free < 4:
            sys.exit("REFUSED: C: free %.1f GB < 4" % free)
    except Exception:
        pass
    env = dict(os.environ)
    env["USERPROFILE"] = PROFILE
    p = subprocess.Popen([os.path.join(GAME, "TOD.exe")], cwd=GAME, env=env)
    json.dump({"pid": p.pid, "start": time.time()}, open(STATE, "w"))
    log("launched test game pid %d (USERPROFILE=%s)" % (p.pid, PROFILE))
    print("pid", p.pid)
    if wait:
        for i in range(60):
            time.sleep(1)
            ws = windows_of(p.pid)
            if ws and ws[0][1] > 200:
                print("window after %ds: %dx%d" % (i + 1, ws[0][1], ws[0][2]))
                return
            if p.poll() is not None:
                sys.exit("game exited code %s" % p.returncode)
        print("no window after 60 s")


def alive(pid):
    return any(p == pid for _, p in tod_procs())


def cmd_close():
    st = state()
    pid = st.get("pid")
    if not pid or not alive(pid):
        print("not running"); return
    for h, _, _ in windows_of(pid):
        user32.PostMessageW(h, 0x0010, 0, 0)    # WM_CLOSE
    for _ in range(20):
        time.sleep(0.5)
        if not alive(pid):
            break
    if alive(pid):
        subprocess.run(["taskkill", "/PID", str(pid), "/F"], capture_output=True)
        time.sleep(1)
    log("closed our test game pid %d (alive after: %s)" % (pid, alive(pid)))
    print("closed", pid, "alive:", alive(pid))


def cmd_checksaves():
    want = {}
    for line in open(SAVE_LIST):
        n, size, mt, hsh = line.split()
        want[n] = hsh
    bad = []
    have = sorted(os.listdir(USER_SAVES))
    for n in have:
        hsh = hashlib.sha256(open(os.path.join(USER_SAVES, n), "rb").read()).hexdigest().upper()
        if want.get(n) != hsh:
            bad.append(n)
    extra = set(have) ^ set(want)
    import winreg
    k = winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Software\Eidos\Total Overdose")
    cur = {"XRes": winreg.QueryValueEx(k, "XRes")[0], "YRes": winreg.QueryValueEx(k, "YRes")[0],
           "lastwrite": winreg.QueryInfoKey(k)[2]}
    base_f = os.path.join(LAB, "saveiso", "backup", "registry_baseline.json")
    if not os.path.exists(base_f):
        json.dump(cur, open(base_f, "w"))
    regok = json.load(open(base_f)) == cur
    print("user saves identical:", not bad and not extra, "changed:", bad, "added/missing:", sorted(extra),
          "| registry key unchanged (values + last-write time):", regok, cur)
    log("checksaves: identical=%s changed=%s extra=%s reg_ok=%s" % (not bad and not extra, bad, sorted(extra), regok))


def cmd_hold(key, secs, capdir=None, fps=25, scale=0.5, also=None, mouse=0, presskeys=None, click_every=0.0):
    h = need_fg()
    g = Grabber(h) if capdir else None
    frames = []
    keys = [k for k in [key] + (also.split(",") if also else []) if k and k.upper() != "NONE"]
    last_click = -1e9
    for k in keys:
        key_event(k, False)
    t0 = time.time(); n = 0
    tick0 = kernel32.GetTickCount()
    try:
        while time.time() - t0 < secs:
            if user32.GetForegroundWindow() != h:
                print("lost foreground; stopping"); break
            if mouse:
                mouse_move(mouse)
            if click_every and time.time() - last_click >= click_every:
                last_click = time.time(); mouse_click()
            if g:
                frames.append((time.time() - t0, g.grab()))
            n += 1
            nxt = t0 + n / fps
            d = nxt - time.time()
            if d > 0:
                time.sleep(d)
    finally:
        for k in keys:
            key_event(k, True)
        print("ticks %d %d key %s" % (tick0, kernel32.GetTickCount(), key))
        log("hold %s %.1fs ticks %d..%d cap %s" % (key, secs, tick0, kernel32.GetTickCount(), capdir))
    if g:
        os.makedirs(capdir, exist_ok=True)
        for i, (t, raw) in enumerate(frames):
            g.to_image(raw, scale).save(os.path.join(capdir, "f%04d.png" % i))
        json.dump({"fps_target": fps, "times": [t for t, _ in frames], "w": g.w, "h": g.h, "scale": scale},
                  open(os.path.join(capdir, "frames.json"), "w"))
        g.close()
        print("captured %d frames in %.2fs to %s" % (len(frames), frames[-1][0] if frames else 0, capdir))


def main():
    a = sys.argv[1:]
    if not a:
        print(__doc__); return
    c = a[0]
    if c == "launch":
        cmd_launch("--no-wait" not in a)
    elif c == "status":
        st = state(); print("state", st, "tod procs", tod_procs())
        if st.get("pid"):
            print("windows", windows_of(st["pid"]), "fg", user32.GetForegroundWindow())
    elif c == "shot":
        sc = float(a[a.index("--scale") + 1]) if "--scale" in a else 1.0
        cmd_shot(a[1], sc)
    elif c == "keys":
        for tok in a[1].split(","):
            tok = tok.strip()
            if tok.startswith("wait:"):
                time.sleep(float(tok[5:]))
            elif tok.startswith("hold:"):          # hold:KEY:secs
                _, k, s = tok.split(":"); h = need_fg(); key_event(k, False); time.sleep(float(s)); key_event(k, True)
            elif tok.startswith("mouse:"):
                need_fg(); mouse_move(int(tok[6:]))
            elif tok == "click":
                need_fg(); mouse_click()
            else:
                press(tok)
            time.sleep(0.12)
        print("sent", a[1])
    elif c == "hold":
        def opt(n, d, f=str):
            return f(a[a.index(n) + 1]) if n in a else d
        cmd_hold(a[1], float(a[2]), opt("--cap", None), opt("--fps", 25, float), opt("--scale", 0.5, float),
                 opt("--also", None), opt("--mouse", 0, int), click_every=opt("--click-every", 0.0, float))
    elif c == "close":
        cmd_close()
    elif c == "checksaves":
        cmd_checksaves()
    else:
        print(__doc__)


if __name__ == "__main__":
    main()
