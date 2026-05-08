"""Smoke test: verify the advisor tool API call works."""
import anthropic
import os

client = anthropic.Anthropic(api_key=os.environ.get("ANTHROPIC_API_KEY"))

response = client.beta.messages.create(
    model="claude-sonnet-4-6",
    max_tokens=500,
    betas=["advisor-tool-2026-03-01"],
    tools=[{
        "type": "advisor_20260301",
        "name": "advisor",
        "model": "claude-opus-4-7",
        "max_uses": 1,
    }],
    messages=[{"role": "user", "content": "What is 2+2? Think carefully."}],
)

print(f"Stop reason: {response.stop_reason}")
print(f"Content blocks: {len(response.content)}")
for i, block in enumerate(response.content):
    print(f"  [{i}] type={block.type}")
    if block.type == "text":
        print(f"       text={block.text[:200]}")
    elif block.type == "server_tool_use":
        print(f"       name={block.name} input={block.input}")
    elif block.type == "advisor_tool_result":
        content = block.content
        # SDK may return content as dict or object depending on version
        c_type = content.get("type") if isinstance(content, dict) else getattr(content, "type", None)
        print(f"       content.type={c_type}")
        if c_type == "advisor_result":
            c_text = content.get("text") if isinstance(content, dict) else content.text
            print(f"       advice={c_text[:200]}")
        elif c_type == "advisor_redacted_result":
            print(f"       (encrypted — opaque blob, round-trip verbatim)")
        else:
            print(f"       raw content={str(content)[:200]}")

print(f"\nUsage: input={response.usage.input_tokens} output={response.usage.output_tokens}")
if hasattr(response.usage, "iterations"):
    for it in response.usage.iterations:
        it_type = getattr(it, "type", "unknown")
        print(f"  iteration: type={it_type} in={it.input_tokens} out={it.output_tokens}")
        if it_type == "advisor_message":
            print(f"    advisor model={getattr(it, 'model', 'unknown')}")
