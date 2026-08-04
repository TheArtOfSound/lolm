from lolm.capability_router import TaskKind
from lolm.task_profiler import profile_task


def test_bare_python_version_is_not_assumed_current():
    profile = profile_task("According to these sources, what Python version is required?", supplied_sources=True)
    assert profile.kind == TaskKind.FACTUAL_QA
    assert profile.requires_current_information is False
    assert profile.requires_retrieval is True
    assert "freshness" not in profile.tags


def test_latest_version_is_current_and_requires_retrieval():
    profile = profile_task("What is the latest Python version?")
    assert profile.kind == TaskKind.CURRENT_QA
    assert profile.requires_current_information is True
    assert profile.requires_retrieval is True
    assert profile.requires_tools is True


def test_repository_action_dominates_research_wording():
    profile = profile_task(
        "Research the latest release and fix the existing repository",
        has_repository=True,
        supplied_sources=True,
    )
    assert profile.kind == TaskKind.REPO_EDIT
    assert profile.requires_execution is True
    assert profile.requires_structured_output is True
    assert profile.repository_context is True


def test_research_without_repository_action_remains_research():
    profile = profile_task("Research and compare three coding-agent benchmarks")
    assert profile.kind == TaskKind.RESEARCH
    assert profile.requires_execution is False
    assert profile.requires_retrieval is True


def test_current_release_inside_repo_edit_keeps_both_requirements():
    profile = profile_task(
        "Update this repository to the current release",
        has_repository=True,
    )
    assert profile.kind == TaskKind.REPO_EDIT
    assert profile.requires_execution is True
    assert profile.requires_current_information is True
    assert profile.requires_retrieval is True
