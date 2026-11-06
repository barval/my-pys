from webui.wizard import advance, load_progress, save_progress


def test_missing_progress_starts_at_first_step(tmp_path):
    progress = load_progress(tmp_path / "speaker-a.json", first_step=2)
    assert progress.step == 2
    assert progress.done == ()


def test_advance_marks_done_and_moves_forward(tmp_path):
    path = tmp_path / "speaker-a.json"
    progress = load_progress(path, first_step=2)
    progress = advance(progress, "bind")
    assert "bind" in progress.done
    assert progress.step == 3
    save_progress(path, progress)
    assert load_progress(path).step == 3


def test_skip_also_moves_forward(tmp_path):
    progress = load_progress(tmp_path / "speaker-a.json", first_step=2)
    progress = advance(progress, "bind", skipped=True)
    assert "bind" in progress.skipped
    assert progress.step == 3
