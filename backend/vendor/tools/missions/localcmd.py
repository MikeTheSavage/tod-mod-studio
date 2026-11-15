"""Resolve a receiver-local (negative) command id for a class: method index = -id - 2 in the class's method table
sorted by command id (FUN_0048A7E0; proven for TriggerCtrl -4 -> 450 and master_mission_ctrl -10 -> 618).
  python localcmd.py CLASS -43 -24 ...    |   python localcmd.py --table CLASS"""
import json, os, sys
HERE = os.path.dirname(os.path.abspath(__file__))
C = {c['name']: c for c in json.load(open(os.path.join(HERE, 'data', 'classes.json') if os.path.exists(os.path.join(HERE, 'data', 'classes.json')) else os.path.join(HERE, '..', 'out', 'classes.json')))}
def table(cn):
    return sorted(C[cn]['methods'], key=lambda m: m['id'])
if __name__ == '__main__':
    if sys.argv[1] == '--table':
        for i, m in enumerate(table(sys.argv[2])):
            print(i, m['id'], m['command'], m['thread'], m['method'])
    else:
        t = table(sys.argv[1])
        for x in sys.argv[2:]:
            v = int(x, 0)
            k = -v - 2
            print(x, '->', k, (t[k]['id'], t[k]['command']) if 0 <= k < len(t) else 'out of range')
