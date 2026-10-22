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


def test_cli_with_images_reads_them_instead_of_running_toolless(tmp_path, monkeypatch):
    monkeypatch.setenv("PAGES_LLM", "claude-cli")
    (tmp_path / "sheet-01.png").write_bytes(b"png")
    seen = []
    monkeypatch.setattr(subprocess, "run", lambda cmd, **kw: (seen.append(cmd), subprocess.CompletedProcess(
        cmd, 0, json.dumps({"is_error": False, "structured_output": {"x": 1}}), ""))[1])
    assert llm.ask("pick", X, images=[tmp_path / "sheet-01.png"]).x == 1
    cmd = seen[0]
    assert str((tmp_path / "sheet-01.png").resolve()) in cmd[cmd.index("-p") + 1] and "--tools" not in cmd
    assert cmd[cmd.index("--allowedTools") + 1] == "Read" and cmd[cmd.index("--add-dir") + 1] == str(tmp_path.resolve())


def test_bedrock_sends_images_before_the_text(tmp_path, monkeypatch):
    monkeypatch.setenv("PAGES_LLM", "bedrock")
    (tmp_path / "a.png").write_bytes(b"png")
    sent = {}

    class Messages:
        def parse(self, **kw):
            sent.update(kw)
            return types.SimpleNamespace(stop_reason="end_turn", parsed_output=X(x=3), content=[])

    monkeypatch.setitem(sys.modules, "anthropic", types.SimpleNamespace(
        AnthropicBedrockMantle=lambda aws_region: types.SimpleNamespace(messages=Messages())))
    assert llm.ask("pick", X, images=[tmp_path / "a.png"]).x == 3
    image, text = sent["messages"][0]["content"]
    assert image["type"] == "image" and image["source"]["data"] == "cG5n" and image["source"]["media_type"] == "image/png"
    assert text == {"type": "text", "text": "pick"}
