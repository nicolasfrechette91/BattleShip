#! python3
"""Open one episode in the replay viewer without a console window.

    pythonw <repo>\\replay\\replay_open.pyw <episode folder | actions.jsonl> [viewer options]

Used by the Explorer "Replay episode" entry (replay_context_menu_install.reg)
and by the browser's Play button. Works from any current directory. A path
that is not a replayable episode, or a failure before the viewer window opens,
is reported in a message box; everything else is shown by the viewer itself.
Output goes to replay/_local/launcher.log.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import replay_windowless  # noqa: E402

TITLE = "Replay episode"


def main() -> int:
    if len(sys.argv) < 2:
        replay_windowless.message(TITLE, "Usage: replay_open.pyw <episode folder | actions.jsonl> [viewer options]")
        return 2
    target = sys.argv[1]
    from replay_episode import EpisodeError, load_episode

    try:
        load_episode(target)
    except EpisodeError as exc:
        replay_windowless.message(
            TITLE, f"Not a replayable episode:\n{target}\n\n{exc}\n\n"
                   "Choose an episode folder that contains actions.jsonl and metadata.json, or its actions.jsonl.")
        return 2
    import replay

    start = replay_windowless.log_offset()
    code = replay.main(sys.argv[1:])
    if code == 2:  # refused before the viewer window opened (e.g. executable or tkinter missing)
        replay_windowless.message(TITLE, f"The viewer could not start:\n\n{replay_windowless.log_since(start)}\n\n"
                                         f"Log: {replay_windowless.LOG_FILE}")
    return code


if __name__ == "__main__":
    replay_windowless.run("replay_open", main, title=TITLE)
