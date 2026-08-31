"""
agent/smoke_test.py -- proves agent/llm.py's client actually reaches the
real Claude API and gets a real response back. Not part of `pytest
tests/agent/` on purpose: it spends real money on every run, unlike the
tool fixtures, which only touch BigQuery. Run on demand:

    python -m agent.smoke_test
"""
from agent.llm import MODEL_ID, get_client


def main():
    client = get_client()
    response = client.messages.create(
        model=MODEL_ID,
        max_tokens=64,
        messages=[{"role": "user", "content": "Reply with exactly: TrendShelf agent smoke test OK"}],
    )
    text = "".join(block.text for block in response.content if block.type == "text")
    print("model:", response.model)
    print("stop_reason:", response.stop_reason)
    print("response text:", text)
    print("input_tokens:", response.usage.input_tokens)
    print("output_tokens:", response.usage.output_tokens)
    return response


if __name__ == "__main__":
    main()
