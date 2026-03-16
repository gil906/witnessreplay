"""Regression tests for Detective Ray interview guardrails."""

import pytest

from app.agents.scene_agent import SceneReconstructionAgent


@pytest.fixture
def agent(monkeypatch):
    """Create an agent instance without initializing remote model clients."""
    monkeypatch.setattr(SceneReconstructionAgent, "_initialize_model", lambda self: None)
    return SceneReconstructionAgent("test-session")


def test_duplicate_questions_are_deduplicated(agent):
    response = "Please tell me what happened. Tell me what happened."

    repaired = agent._dedupe_response_sentences(response)

    assert repaired == "Please tell me what happened."


def test_first_turn_restart_like_response_is_repaired(agent):
    repaired = agent._ensure_follow_up_response(
        "I would like to report a crime.",
        "I'm Detective Rav. Please tell me what happened. Tell me what happened.",
    )

    normalized = agent._normalize_text(repaired)
    assert "detective rav" not in normalized
    assert normalized.count("tell me what happened") == 1


def test_missing_time_follow_up_is_enforced(agent):
    repaired = agent._ensure_follow_up_response(
        "A man stole a purse from an older woman in Seattle.",
        "Thank you for reporting this. Can you describe the person who took the purse?",
    )

    normalized = agent._normalize_text(repaired)
    assert "about what time did this happen" in normalized
    assert "describe the person" not in normalized


def test_limited_visibility_phrase_does_not_end_interview(agent):
    agent.conversation_history = [
        {"role": "assistant", "content": "Can you describe the person who was stealing the purse?"}
    ]

    assert agent._witness_signaled_completion(
        "It was a man wearing black clothes, and that's all I can see."
    ) is False


def test_prompted_no_more_response_can_complete(agent):
    agent.conversation_history = [
        {"role": "assistant", "content": "Is there anything else you'd like to add?"}
    ]

    assert agent._witness_signaled_completion("No, that's all.") is True
