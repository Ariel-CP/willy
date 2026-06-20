from pathlib import Path

from app.learned_memory import LearnedMemory


def test_record_project_event_persists_project_memory(tmp_path: Path) -> None:
    memory = LearnedMemory(base_dir=str(tmp_path))
    project_dir = tmp_path / "project_a"
    project_dir.mkdir()

    memory.record_project_event(
        project_path=str(project_dir),
        action="compile",
        success=True,
        summary="compile env=esp32dev",
    )

    project_memory_file = project_dir / ".willy_project_memory.json"
    assert project_memory_file.exists()

    prompt_summary = memory.summary_for_prompt(project_path=str(project_dir))
    assert "LEARNED_CONTEXT" in prompt_summary
    assert "project_lessons" in prompt_summary


def test_promotes_stable_project_lesson_to_global(tmp_path: Path) -> None:
    memory = LearnedMemory(base_dir=str(tmp_path))
    project_dir = tmp_path / "project_b"
    project_dir.mkdir()

    for _ in range(3):
        memory.record_project_event(
            project_path=str(project_dir),
            action="upload",
            success=True,
            summary="upload env=uno port=/dev/ttyUSB0",
        )

    global_memory_file = tmp_path / "willy_global_lab_memory.json"
    assert global_memory_file.exists()

    prompt_summary = memory.summary_for_prompt(project_path=str(project_dir))
    assert "global_lab_lessons" in prompt_summary


def test_infers_mechatronics_domain_from_summary(tmp_path: Path) -> None:
    memory = LearnedMemory(base_dir=str(tmp_path))
    project_dir = tmp_path / "project_c"
    project_dir.mkdir()

    memory.record_project_event(
        project_path=str(project_dir),
        action="compile",
        success=False,
        summary="pid control loop overflow at high pwm",
        error="stability issue",
    )

    prompt_summary = memory.summary_for_prompt(project_path=str(project_dir))
    assert "[control]" in prompt_summary
