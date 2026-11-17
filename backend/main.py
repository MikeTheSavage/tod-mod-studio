"""TOD Mod Studio: a standalone level and data editor for Total Overdose (2005).

  TODModStudio.exe                 opens the app window
  TODModStudio.exe Mod.todmod      opens it and offers to add the file (also .todcollection, .todpiece)
  TODModStudio.exe --restore-vanilla [--remove-backups]   no window: put the game back to its own files (the uninstaller uses this)
  python main.py --server [--port 8765]   API + UI only (open http://127.0.0.1:8765 in a browser; development)
"""
import argparse
import os
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)

from todms import server  # noqa: E402

TITLE = 'TOD Mod Studio'


def main():
    from todms import cli
    rc = cli.main(sys.argv[1:])
    if rc is not None:
        return rc
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--server', action='store_true', help='no window: serve the UI and the API for a browser')
    ap.add_argument('--port', type=int, default=0)
    ap.add_argument('files', nargs='*', help='.todmod / .todcollection / .todpiece files to offer to add (a double click in Windows)')
    ap.add_argument('--selftest', metavar='OUT.json', help='start, answer one status request, write the result, exit')
    a = ap.parse_args()
    from todms import paths
    paths.ensure_cpu_guard()          # keep builds off CPU cores that divide packed floats wrongly
    if a.server:
        server.DEV = True
    server.OPEN_FILES.extend(cli.open_files(a.files))
    srv = server.serve(a.port or (8765 if a.server else 0))
    port = srv.server_address[1]
    url = 'http://127.0.0.1:%d/' % port
    if a.selftest:
        import json
        import urllib.request
        st = json.load(urllib.request.urlopen(url + 'api/status', timeout=60))
        html = urllib.request.urlopen(url, timeout=30).read()
        out = dict(ok=True, url=url, ready=st.get('ready'), ui_bytes=len(html), has_ui=b'todms-token' in html,
                   frozen=getattr(sys, 'frozen', False), python=sys.version.split()[0], missing=st.get('missing'))
        try:
            import fragtool, submaptool, missiontool, weapons, vehtool, locotool, camtool, savefile  # noqa: F401
            out['tools_import'] = True
        except Exception as e:
            out['tools_import'] = str(e)
        open(a.selftest, 'w').write(json.dumps(out, indent=1))
        srv.shutdown()
        return 0
    if a.server:
        if sys.stdout:
            print('TOD Mod Studio at %s (Ctrl+C to stop)' % url, flush=True)
        try:
            while True:
                time.sleep(3600)
        except KeyboardInterrupt:
            return 0
    import webview
    win = webview.create_window(TITLE, url, width=1600, height=960, min_size=(1100, 700), background_color='#11151b',
                                maximized=True)
    server.WINDOW = win
    webview.start()
    srv.shutdown()
    return 0


if __name__ == '__main__':
    sys.exit(main())
