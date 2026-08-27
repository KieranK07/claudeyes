#!/usr/bin/env python3
"""Stands in for the Swift shim so the whole pipeline can be exercised on any
machine. Emits the same JSONL contract, posts the same actions over the socket.

    python3 tools/fake_capture.py | python3 -m claudeyes.daemon --db /tmp/cy.db
"""
import json, os, sys, time, threading
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from claudeyes.sources.socket_source import post, DEFAULT_PATH

SOCK = os.environ.get("CLAUDEYES_SOCK", DEFAULT_PATH)

W, H = 1512, 982
SAFARI = "Safari"
SCRIPT = [
    (0.0,  {"kind":"mouse_move","params":{"x0":400,"y0":300,"x1":690,"y1":450,"app":SAFARI}},
           [{"x":390,"y":290,"w":320,"h":180,"app":SAFARI}]),
    (0.35, None, [{"x":600,"y":420,"w":190,"h":64,"app":SAFARI}]),
    (0.7,  {"kind":"click","params":{"bbox":{"x":620,"y":430,"w":150,"h":44},
                                     "window":{"x":0,"y":0,"w":W,"h":H},"app":SAFARI}},
           [{"x":620,"y":430,"w":150,"h":44,"app":SAFARI}]),
    (1.0,  None, [{"x":0,"y":90,"w":W,"h":H-90,"app":SAFARI}]),
    (1.6,  None, [{"x":W-380,"y":40,"w":360,"h":90,"app":"Notification Center"}]),
    (2.1,  {"kind":"scroll","params":{"viewport":{"x":0,"y":90,"w":W,"h":H-90},"app":SAFARI}},
           [{"x":0,"y":90,"w":W,"h":H-90,"app":SAFARI}]),
    (2.4,  None, [{"x":0,"y":90,"w":W,"h":H-90,"app":SAFARI}]),
    (3.0,  None, [{"x":40,"y":H-260,"w":520,"h":220,"app":"Terminal"}]),
]

def actions(t0):
    for dt, act, _ in SCRIPT:
        if act is None:
            continue
        while time.time() - t0 < dt - 0.02:
            time.sleep(0.005)
        act["t"] = time.time()
        act["source"] = "agent"
        try:
            post(act, SOCK)
        except OSError as e:
            print(f"fake_capture: action post failed: {e}", file=sys.stderr)

def main():
    print(json.dumps({"type":"hello","width":W,"height":H,"t":time.time()}), flush=True)
    time.sleep(0.3)  # let the daemon bind the socket
    t0 = time.time()
    threading.Thread(target=actions, args=(t0,), daemon=True).start()
    for i, (dt, _, dirty) in enumerate(SCRIPT):
        while time.time() - t0 < dt:
            time.sleep(0.005)
        time.sleep(0.03)  # actions are posted just before their frame lands
        print(json.dumps({"t": time.time(), "frame": i, "dirty": dirty}), flush=True)
    time.sleep(0.4)

if __name__ == "__main__":
    main()
