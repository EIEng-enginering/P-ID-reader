"""run_task(on_finish=...): a tab's busy state is released in the same slot that clears window.task (pre-existing race, found in the
full-suite run: test_wp456_gui::test_stale_result_does_not_populate_another_page failed 1 run in 8 on clean main c91ebe6)."""
import time

from test_wp456_gui import qapp, wait_idle, win  # noqa: F401  (fixtures)


def test_on_finish_runs_when_the_task_is_cleared_on_success(win, qapp):
    seen = []
    assert win.run_task("ok", lambda report, cancelled: 1, lambda r: seen.append(("done", win.task)), on_finish=lambda: seen.append(("finish", win.task)))
    wait_idle(win, qapp)
    assert seen[0] == ("finish", None) and seen[1] == ("done", None)


def test_on_finish_runs_on_error_and_after_cancel(win, qapp):
    seen = []

    def boom(report, cancelled):
        raise ValueError("expected failure")
    win.run_task("fails", boom, lambda r: None, on_finish=lambda: seen.append("error"))
    wait_idle(win, qapp)
    assert seen == ["error"] and any("WARN" in str(m) for m in win.shown)

    def spin(report, cancelled):
        t0 = time.time()
        while not cancelled() and time.time() - t0 < 20:
            time.sleep(.01)
    win.run_task("cancelled", spin, lambda r: None, on_finish=lambda: seen.append("stopped"))
    t0 = time.time()
    while win.task is None and time.time() - t0 < 5:
        qapp.processEvents()
    win.task.cancel()
    wait_idle(win, qapp)
    assert seen == ["error", "stopped"]


def test_a_refused_start_returns_false_and_never_runs_the_other_callback(win, qapp):
    seen = []

    def spin(report, cancelled):
        t0 = time.time()
        while not cancelled() and time.time() - t0 < 20:
            time.sleep(.01)
    assert win.run_task("first", spin, lambda r: None, on_finish=lambda: seen.append("first"))
    assert win.run_task("second", spin, lambda r: None, on_finish=lambda: seen.append("second")) is False
    win.task.cancel()
    wait_idle(win, qapp)
    assert seen == ["first"]
