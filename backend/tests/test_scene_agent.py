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
    assert "crime" in normalized
    assert "tell me a little more" in normalized


def test_car_crash_report_intent_gets_contextual_opening_follow_up(agent):
    repaired = agent._ensure_follow_up_response(
        "I want to report a car crash.",
        "Please tell me what happened.",
    )

    normalized = agent._normalize_text(repaired)
    assert "car crash" in normalized
    assert "tell me a little more" in normalized
    assert "what day did this happen" not in normalized


def test_collect_report_car_crash_intro_is_repaired_contextually(agent):
    repaired = agent._ensure_follow_up_response(
        "Can you collect the report against the car crash?",
        "I'm Detective Ray. Please tell me what happened.",
    )

    normalized = agent._normalize_text(repaired)
    assert "detective ray" not in normalized
    assert "car crash" in normalized
    assert "tell me a little more" in normalized


def test_missing_time_follow_up_is_enforced(agent):
    repaired = agent._ensure_follow_up_response(
        "A man stole a purse from an older woman in Seattle.",
        "Thank you for reporting this. Can you describe the person who took the purse?",
    )

    normalized = agent._normalize_text(repaired)
    assert "thank you for reporting this" not in normalized
    assert "what day did this happen" in normalized
    assert "about what time was it" in normalized
    assert "describe the person" not in normalized


def test_template_greeting_is_plain_and_conversational(agent):
    agent.set_template({"name": "Traffic Accident", "initial_questions": ["Can you describe what happened?"]})

    greeting = agent._generate_template_greeting()

    assert "**" not in greeting
    assert "Start wherever it makes sense" in greeting
    assert "traffic accident" in greeting.lower()


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
