"""Ask Claude for a pydantic-shaped answer: the claude CLI locally, Bedrock on the server."""
import json
import os
import subprocess
from typing import TypeVar

from pydantic import BaseModel

M = TypeVar("M", bound=BaseModel)


class LLMError(Exception):
    pass


def ask(prompt: str, schema: type[M]) -> M:
    if os.environ.get("PAGES_LLM", "claude-cli") == "bedrock":
        return _bedrock(prompt, schema)
    return _cli(prompt, schema)


def _cli(prompt: str, schema: type[M]) -> M:
    cmd = ["claude", "-p", prompt, "--json-schema", json.dumps(schema.model_json_schema()),
           "--output-format", "json", "--model", "opus", "--tools", ""]
    done = subprocess.run(cmd, capture_output=True, text=True, timeout=900)
    if done.returncode != 0:
        raise LLMError(done.stderr)
    out = json.loads(done.stdout)
    if out.get("is_error"):
        raise LLMError(out.get("result"))
    if out.get("structured_output") is None:
        raise LLMError(f"no structured_output: {out.get('result')}")
    return schema.model_validate(out["structured_output"])


def _bedrock(prompt: str, schema: type[M]) -> M:
    from anthropic import AnthropicBedrockMantle

    client = AnthropicBedrockMantle(aws_region=os.environ.get("PAGES_BEDROCK_REGION", "ap-south-1"))
    msg = client.messages.parse(model="anthropic.claude-opus-5-5", max_tokens=16000,
                                messages=[{"role": "user", "content": prompt}], output_format=schema)
    if msg.stop_reason == "refusal":
        raise LLMError(f"refused: {msg.content}")
    return msg.parsed_output
