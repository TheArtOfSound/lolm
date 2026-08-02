from lolm.capability_router import (
    AgentRole,
    ModelCapability,
    ModelPerformance,
    TaskKind,
    TaskProfile,
    profile_task,
    route_models,
)


def _model(model_id, provider, **overrides):
    values = dict(
        context_tokens=100_000,
        reasoning=0.7,
        coding=0.7,
        repo_editing=0.7,
        tool_use=0.7,
        structured_output=0.7,
        factuality=0.7,
        verification=0.7,
        latency=0.5,
        cost=0.5,
    )
    values.update(overrides)
    return ModelCapability(model_id, provider, **values)


def test_profiles_current_question_as_retrieval_required():
    profile = profile_task("What is the latest released version of this model?")
    assert profile.kind == TaskKind.CURRENT_QA
    assert profile.requires_current_information is True
    assert profile.requires_retrieval is True
    assert profile.requires_tools is True


def test_profiles_repository_code_task():
    profile = profile_task("Fix the parser bug in this existing GitHub repository", has_repository=True)
    assert profile.kind == TaskKind.REPO_EDIT
    assert profile.repository_context is True
    assert profile.requires_execution is True
    assert profile.requires_structured_output is True


def test_hard_filters_tool_incapable_executor():
    profile = TaskProfile(
        kind=TaskKind.SHELL_OPERATION,
        requires_tools=True,
        requires_execution=True,
        requires_structured_output=True,
        estimated_context_tokens=1000,
    )
    weak = _model("weak", "p1", tool_use=0.2)
    strong = _model("strong", "p2", tool_use=0.9)
    plan = route_models(profile, registry=[weak, strong])
    executor = plan.model_for(AgentRole.EXECUTOR)
    assert executor is not None
    assert executor.model_id == "strong"
    assert any(model == "weak" and "tool_use_below_floor" in reason for model, reason in plan.rejected)


def test_measured_results_override_registry_prior_after_enough_attempts():
    profile = TaskProfile(
        kind=TaskKind.CODE_GENERATION,
        language="python",
        requires_tools=True,
        requires_execution=True,
        requires_structured_output=True,
        estimated_context_tokens=1000,
    )
    favorite = _model("favorite", "p1", coding=0.95, tool_use=0.95, structured_output=0.95)
    reliable = _model("reliable", "p2", coding=0.75, tool_use=0.75, structured_output=0.75)
    perf = {
        ("favorite", profile.bucket): ModelPerformance(
            "favorite", profile.bucket, attempts=200, pass_rate=0.30,
            format_error_rate=0.20, tool_error_rate=0.20,
        ),
        ("reliable", profile.bucket): ModelPerformance(
            "reliable", profile.bucket, attempts=200, pass_rate=0.88,
            format_error_rate=0.01, tool_error_rate=0.01,
        ),
    }
    plan = route_models(profile, registry=[favorite, reliable], performance=perf)
    assert plan.model_for(AgentRole.EXECUTOR).model_id == "reliable"


def test_five_attempts_do_not_overrule_broad_prior():
    profile = TaskProfile(
        kind=TaskKind.CODE_GENERATION,
        requires_tools=True,
        requires_execution=True,
        requires_structured_output=True,
        estimated_context_tokens=1000,
    )
    strong = _model("strong", "p1", coding=0.95, tool_use=0.95, structured_output=0.95)
    uncertain = _model("uncertain", "p2", coding=0.66, tool_use=0.66, structured_output=0.66)
    perf = {
        ("uncertain", profile.bucket): ModelPerformance(
            "uncertain", profile.bucket, attempts=5, pass_rate=1.0,
        )
    }
    plan = route_models(profile, registry=[strong, uncertain], performance=perf)
    assert plan.model_for(AgentRole.EXECUTOR).model_id == "strong"


def test_verifier_is_penalized_for_self_approval():
    profile = TaskProfile(
        kind=TaskKind.CODE_GENERATION,
        requires_tools=True,
        requires_execution=True,
        requires_structured_output=True,
        estimated_context_tokens=1000,
    )
    best = _model(
        "best", "provider-a", reasoning=0.95, coding=0.95,
        tool_use=0.95, structured_output=0.95, verification=0.95,
    )
    independent = _model(
        "independent", "provider-b", reasoning=0.82, coding=0.72,
        tool_use=0.75, structured_output=0.80, verification=0.90,
    )
    plan = route_models(profile, registry=[best, independent])
    executor = plan.model_for(AgentRole.EXECUTOR)
    verifier = plan.model_for(AgentRole.VERIFIER)
    assert executor.model_id == "best"
    assert verifier.model_id == "independent"


def test_provider_availability_is_a_hard_gate():
    profile = TaskProfile(kind=TaskKind.FACTUAL_QA, estimated_context_tokens=1000)
    unavailable = _model("unavailable", "p1", factuality=0.99)
    available = _model("available", "p2", factuality=0.70)
    plan = route_models(
        profile,
        registry=[unavailable, available],
        available_models=["available"],
    )
    assert all(item.model_id == "available" for item in plan.assignments)
    assert any(model == "unavailable" and reason == "provider_unavailable" for model, reason in plan.rejected)


def test_insufficient_context_is_rejected():
    profile = TaskProfile(kind=TaskKind.REPO_EDIT, estimated_context_tokens=50_000)
    small = _model("small", "p1", context_tokens=8_000)
    large = _model("large", "p2", context_tokens=100_000)
    plan = route_models(profile, registry=[small, large])
    assert all(item.model_id == "large" for item in plan.assignments)
    assert any(model == "small" and "insufficient_context" in reason for model, reason in plan.rejected)
