"""Manual test: verify llm_call_with_advisor() works end-to-end."""
import anthropic
import os

from evaluation.token_tracker import TokenTracker, llm_call_with_advisor

client = anthropic.Anthropic(api_key=os.environ.get("ANTHROPIC_API_KEY"))
tracker = TokenTracker()

result = llm_call_with_advisor(
    client, tracker, "test",
    model="claude-sonnet-4-6",
    max_tokens=500,
    temperature=0.0,
    system="You are a helpful assistant.",
    messages=[{"role": "user", "content": "What is the capital of France?"}],
    max_advisor_uses=1,
)

print(f"Response: {result[:200]}")
print(f"Token summary: {tracker.summary()}")
print(f"By agent: {tracker.by_agent()}")
