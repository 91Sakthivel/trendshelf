"""
agent/llm.py -- the single seam for constructing the Claude client.

Currently: direct Anthropic API, key from ANTHROPIC_API_KEY (.env, never
hardcoded, never committed). Vertex AI was the original Phase 2 design and
its architectural rationale (service-account auth, no API key, no
Marketplace billing surface) still stands -- it's blocked right now
because Claude on Vertex is a Google Cloud Marketplace product, and
Marketplace purchases are disabled on this project's free-trial billing
account. Migration to Vertex is planned around the Nov 6 trial expiry.
See docs/threshold_decisions.md #7.26 for the full record.

get_client() is the ONE function that changes at migration: swap the
Anthropic(...) branch for AnthropicVertex(project_id=..., region=...).
MODEL_ID does not change -- current-generation Claude model IDs are the
same bare string on both the direct API and Vertex.

Deliberately not a provider abstraction class/interface for two cases --
one function with a branch is the whole seam this needs.
"""
import anthropic

import config

# Verified against platform.claude.com/docs/en/about-claude/pricing,
# fetched live 2026-08-31: Claude Sonnet 5, $2/MTok input, $10/MTok output,
# standard (not introductory) pricing -- the previously scheduled Sept 1
# increase to $3/$15 will not occur.
MODEL_ID = "claude-sonnet-5"


def get_client() -> anthropic.Anthropic:
    if config.LLM_PROVIDER == "vertex":
        # Not usable yet -- see the module docstring. Left wired so the
        # Nov 6 migration is a one-line env var flip once Marketplace
        # billing is enabled, not a code change.
        from anthropic import AnthropicVertex
        return AnthropicVertex(project_id=config.PROJECT_ID, region="global")

    if not config.ANTHROPIC_API_KEY:
        raise RuntimeError(
            "ANTHROPIC_API_KEY not set -- required when LLM_PROVIDER=anthropic (the default). "
            "Set it in .env."
        )
    return anthropic.Anthropic(api_key=config.ANTHROPIC_API_KEY)
