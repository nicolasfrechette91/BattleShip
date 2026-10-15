#! python3
"""Replay browser without a console window.

Double-click this file (the .pyw association runs it with pythonw via the py
launcher), or run `pythonw <repo>\\replay\\replay_gui.pyw` from anywhere, e.g.
in a desktop shortcut. It opens the table browser on the existing index at
once and refreshes the index in the background (read-only, incremental; the
very first build takes several minutes). Output goes to
replay/_local/launcher.log; errors are shown in a message box.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import replay_windowless  # noqa: E402


def main() -> int:
    import replay_browser
    import replay_index
    import replay_lab

    first_build = not replay_index.INDEX_DB.exists()
    lab = replay_lab.lab_root()  # the fast-route lab (BATTLESHIP_LAB_ROOT, else C:\BattleShip_lab when it exists)
    app = replay_browser.Browser(lambda: replay_index.load_rows_and_lab(lab), replay_index.scan_all, lab_root=lab)
    app.rescan(first_time=first_build)
    app.root.mainloop()
    return 0


if __name__ == "__main__":
    replay_windowless.run("replay_gui", main, title="Replay browser")
