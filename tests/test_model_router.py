"""Unit tests for Sentinel Adaptive LLM Model Routing."""
from unittest.mock import MagicMock
import pytest

from agent.llm import LLMClient, ModelRouter, TaskType


def test_task_type_resolution():
    """Verify ModelRouter returns appropriate prioritized chains for each task type."""
    code_chain = ModelRouter.get_models_for_task(TaskType.CODE)
    assert len(code_chain) >= 2
    assert "cohere/north-mini-code:free" in code_chain[0] or "code" in code_chain[0]

    reasoning_chain = ModelRouter.get_models_for_task(TaskType.REASONING)
    assert len(reasoning_chain) >= 2
    assert "nemotron" in reasoning_chain[0] or "ultra" in reasoning_chain[0]

    chat_chain = ModelRouter.get_models_for_task(TaskType.CHAT)
    assert len(chat_chain) >= 2

    fast_chain = ModelRouter.get_models_for_task(TaskType.FAST)
    assert len(fast_chain) >= 2


def test_task_type_heuristic_inference():
    """Verify ModelRouter accurately detects task complexity from prompt and system contents."""
    # Code synthesis
    assert ModelRouter.infer_task_type("File: ml/train.py\nRewrite function to remove deprecated parameter") == TaskType.CODE
    assert ModelRouter.infer_task_type("def calculate_metric(df): pass") == TaskType.CODE

    # Root Cause Analysis
    assert ModelRouter.infer_task_type("Investigate root cause and graph causality for failed assertion") == TaskType.REASONING
    assert ModelRouter.infer_task_type("Compute lineage blast radius across DataHub nodes") == TaskType.REASONING

    # Interactive Chat
    assert ModelRouter.infer_task_type("Can you explain what happened during the recent incident?", system="You are the Sentinel on-call chat assistant.") == TaskType.CHAT

    # Fast extraction
    assert ModelRouter.infer_task_type("Extract tags as a JSON object: ['PII', 'Tier-1']") == TaskType.FAST


def test_llm_client_for_task():
    """Verify LLMClient.for_task sets up the expected task profile."""
    client = LLMClient.for_task(TaskType.CODE)
    assert client.task_type == TaskType.CODE

    client_reasoning = LLMClient.for_task(TaskType.REASONING)
    assert client_reasoning.task_type == TaskType.REASONING


def test_llm_client_failover():
    """Verify LLMClient fails over to secondary model when primary model errors."""
    client = LLMClient(api_key="test-key", task_type=TaskType.CODE)
    
    mock_openai = MagicMock()
    # First call on primary model fails (e.g. 404/429)
    # Second call on fallback model succeeds
    mock_success = MagicMock()
    mock_choice = MagicMock()
    mock_choice.message.content = "remediated code"
    mock_choice.message.reasoning = None
    mock_success.choices = [mock_choice]

    mock_openai.chat.completions.create.side_effect = [
        RuntimeError("Primary model rate limited"),
        mock_success,
    ]
    client._client = mock_openai

    result = client.complete("Rewrite function", system="code synthesis", retries=1)
    assert result == "remediated code"
    assert mock_openai.chat.completions.create.call_count == 2
