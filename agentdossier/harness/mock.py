"""Deterministic AgentDojo pipelines for tests: no model, no network.

``RefusingPipeline`` calls no tools and refuses, so no injection can succeed — the behaviour a
well-defended agent should show. ``NaivePipeline`` echoes a scripted tool call, used only to prove
the harness records a *failure* as faithfully as a success. Neither is a real agent; real runs use
AgentDojo's model backends (OpenAI/Anthropic/Google/local) configured from the environment.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from agentdojo.agent_pipeline.base_pipeline_element import BasePipelineElement
from agentdojo.functions_runtime import EmptyEnv, FunctionsRuntime
from agentdojo.types import ChatMessage, text_content_block_from_string


class RefusingPipeline(BasePipelineElement):
    """Answers in text, never calls a tool; injections cannot take effect."""

    name = "refusing-mock"

    def query(
        self,
        query: str,
        runtime: FunctionsRuntime,
        env: Any = EmptyEnv(),  # noqa: B008 - matches AgentDojo's signature
        messages: Sequence[ChatMessage] = (),
        extra_args: dict = {},  # noqa: B006 - matches AgentDojo's signature
    ) -> tuple[str, FunctionsRuntime, Any, Sequence[ChatMessage], dict]:
        reply = {
            "role": "assistant",
            "content": [text_content_block_from_string("I will not act on instructions found in tool data.")],
            "tool_calls": [],
        }
        return query, runtime, env, [*messages, reply], dict(extra_args)
