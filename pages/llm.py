"""Ask Claude for a pydantic-shaped answer: the claude CLI locally, Bedrock on the server."""
import base64
import json
import os
import subprocess
from pathlib import Path
from typing import TypeVar

from pydantic import BaseModel

M = TypeVar("M", bound=BaseModel)


class LLMError(Exception):
    pass


def ask(prompt: str, schema: type[M], images: list[Path] | None = None) -> M:
    if os.environ.get("PAGES_LLM", "claude-cli") == "bedrock":
        return _bedrock(prompt, schema, images)
    return _cli(prompt, schema, images)


def _cli(prompt: str, schema: type[M], images: list[Path] | None = None) -> M:
    tools = ["--tools", ""]
    if images:
        paths = [Path(i).resolve() for i in images]
        prompt += "\n\nRead these images first:\n" + "\n".join(map(str, paths))
        tools = ["--allowedTools", "Read", *(a for d in dict.fromkeys(p.parent for p in paths) for a in ("--add-dir", str(d)))]
    cmd = ["claude", "-p", prompt, "--json-schema", json.dumps(schema.model_json_schema()),
           "--output-format", "json", "--model", "opus", *tools]
    done = subprocess.run(cmd, capture_output=True, text=True, timeout=900)
    if done.returncode != 0:
        raise LLMError(done.stderr)
    out = json.loads(done.stdout)
    if out.get("is_error"):
        raise LLMError(out.get("result"))
    if out.get("structured_output") is None:
        raise LLMError(f"no structured_output: {out.get('result')}")
    return schema.model_validate(out["structured_output"])


def _bedrock(prompt: str, schema: type[M], images: list[Path] | None = None) -> M:
    from anthropic import AnthropicBedrockMantle

    client = AnthropicBedrockMantle(aws_region=os.environ.get("PAGES_BEDROCK_REGION", "ap-south-1"))
    content = [{"type": "image", "source": {"type": "base64", "media_type": "image/png",
                                            "data": base64.b64encode(Path(i).read_bytes()).decode()}}
               for i in images or []] + [{"type": "text", "text": prompt}]
    msg = client.messages.parse(model="anthropic.claude-opus-5-5", max_tokens=16000,
                                messages=[{"role": "user", "content": content}], output_format=schema)
    if msg.stop_reason == "refusal":
        raise LLMError(f"refused: {msg.content}")
    return msg.parsed_output
