import json
import subprocess
import sys
import types

import pytest
from pydantic import BaseModel

from pages import llm


class X(BaseModel):
    x: int


def install_fake_mantle(monkeypatch, stop_reason="end_turn", parsed=None):
    class Messages:
        def parse(self, **kw):
            return types.SimpleNamespace(stop_reason=stop_reason, parsed_output=parsed, content=[])

    class AnthropicBedrockMantle:
        def __init__(self, aws_region):
            self.messages = Messages()

    monkeypatch.setitem(sys.modules, "anthropic", types.SimpleNamespace(AnthropicBedrockMantle=AnthropicBedrockMantle))


def test_cli_backend_validates_structured_output(monkeypatch):
    monkeypatch.setenv("PAGES_LLM", "claude-cli")
    seen = []
    monkeypatch.setattr(subprocess, "run", lambda cmd, **kw: (seen.append(cmd), subprocess.CompletedProcess(
        cmd, 0, json.dumps({"is_error": False, "structured_output": {"x": 2}}), ""))[1])
    assert llm.ask("give x", X).x == 2
    assert "--json-schema" in seen[0] and seen[0][seen[0].index("--model") + 1] == "opus"


def test_cli_error_raises(monkeypatch):
    monkeypatch.setenv("PAGES_LLM", "claude-cli")
    monkeypatch.setattr(subprocess, "run", lambda cmd, **kw: subprocess.CompletedProcess(cmd, 0, json.dumps({"is_error": True, "result": "limit"}), ""))
    with pytest.raises(llm.LLMError, match="limit"):
        llm.ask("x", X)


def test_cli_nonzero_exit_raises(monkeypatch):
    monkeypatch.setenv("PAGES_LLM", "claude-cli")
    monkeypatch.setattr(subprocess, "run", lambda cmd, **kw: subprocess.CompletedProcess(cmd, 1, "", "boom"))
    with pytest.raises(llm.LLMError, match="boom"):
        llm.ask("x", X)


def test_bedrock_refusal_raises(monkeypatch):
    monkeypatch.setenv("PAGES_LLM", "bedrock")
    install_fake_mantle(monkeypatch, stop_reason="refusal")
    with pytest.raises(llm.LLMError, match="refus"):
        llm.ask("x", X)


def test_bedrock_returns_parsed(monkeypatch):
    monkeypatch.setenv("PAGES_LLM", "bedrock")
    install_fake_mantle(monkeypatch, parsed=X(x=5))
    assert llm.ask("x", X).x == 5
