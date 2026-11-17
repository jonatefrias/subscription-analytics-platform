"""AI pull-request review against docs/review_guidelines.md.

Sends the diff of the branch (and the dbt impact report, when given) to Claude with the
project's review guidelines and prints a Markdown review: findings with file, line, severity
and evidence. It complements, never replaces, the tests: CI is the gate, this is a second
pair of eyes on definitions and grain, which tests cannot fully cover.

Cost control: nothing is sent unless ANTHROPIC_API_KEY (or another Anthropic credential) is
available; in CI the job only runs when that secret exists. `--dry-run` prints the exact
prompt instead, so the review can be run for free in an interactive assistant.

Usage:
    python scripts/ai_review.py --base origin/main [--impact impact.md] [--dry-run]
"""

import argparse
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MODEL = "claude-opus-5-5"
MAX_DIFF_CHARS = 400_000  # ~100k tokens; larger PRs should be split, not truncated

SYSTEM_PROMPT = """You review pull requests for a dbt analytics engineering project \
(DuckDB/Snowflake, MetricFlow semantic layer, Dagster orchestration).

Apply the review guidelines below. Report only findings you can support with the diff:
quote the file and line, say what goes wrong (a wrong number, a broken run, a misleading
definition) and how to fix it. Do not comment on formatting or naming style; linters cover that.
Prefer few, well-supported findings over many speculative ones. If the change looks correct,
say so in one line.

Output Markdown with this structure:
### Summary
One or two sentences on what the change does and whether it is safe to merge.
### Findings
A list; each item starts with **Blocker**, **Should fix** or **Question**, then `file:line`,
then the explanation. Write "None." when there are no findings.

<review_guidelines>
{guidelines}
</review_guidelines>"""


def git_diff(base: str) -> str:
    result = subprocess.run(
        ["git", "diff", "--unified=5", f"{base}...HEAD", "--", ".", ":(exclude)data"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=True,
    )
    return result.stdout


def build_messages(diff: str, impact: str | None) -> list[dict]:
    parts = []
    if impact:
        parts.append(f"<dbt_impact_report>\n{impact}\n</dbt_impact_report>")
    parts.append(f"<diff>\n{diff}\n</diff>")
    parts.append("Review this pull request.")
    return [{"role": "user", "content": "\n\n".join(parts)}]


def review(system: str, messages: list[dict]) -> str:
    import anthropic

    client = anthropic.Anthropic()
    try:
        response = client.beta.messages.create(
            model=MODEL,
            max_tokens=16000,
            output_config={"effort": "high"},
            # if a safety classifier declines, the API retries on a suitable model in the same call
            betas=["server-side-fallback-2026-07-01"],
            fallbacks="default",
            system=system,
            messages=messages,
        )
    except anthropic.AuthenticationError:
        return "_AI review skipped: the Anthropic credential was rejected._"
    except anthropic.RateLimitError:
        return "_AI review skipped: rate limited; re-run the job later._"
    except anthropic.APIStatusError as e:
        return f"_AI review skipped: API error {e.status_code}._"
    except anthropic.APIConnectionError:
        return "_AI review skipped: could not reach the API._"

    if response.stop_reason == "refusal":
        return "_AI review declined to review this change._"
    text = "\n".join(block.text for block in response.content if block.type == "text").strip()
    if response.stop_reason == "max_tokens":
        text += "\n\n_(review cut at the output limit)_"
    usage = response.usage
    footer = f"\n\n<sub>{response.model} · {usage.input_tokens:,} input / {usage.output_tokens:,} output tokens</sub>"
    return text + footer


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base", default="origin/main", help="git ref the branch is compared against")
    parser.add_argument("--impact", type=Path, help="Markdown impact report from impact_report.py")
    parser.add_argument("--dry-run", action="store_true", help="print the prompt; do not call the API")
    args = parser.parse_args()

    diff = git_diff(args.base)
    if not diff.strip():
        print("_No changes to review._")
        return 0
    if len(diff) > MAX_DIFF_CHARS:
        print(f"_Diff is {len(diff):,} characters; too large for one review. Split the pull request._")
        return 0

    guidelines = (ROOT / "docs" / "review_guidelines.md").read_text()
    system = SYSTEM_PROMPT.format(guidelines=guidelines)
    impact = args.impact.read_text() if args.impact and args.impact.exists() else None
    messages = build_messages(diff, impact)

    if args.dry_run:
        print(system, "\n\n---\n\n", messages[0]["content"])
        return 0
    print("## AI review\n")
    print(review(system, messages))
    return 0


if __name__ == "__main__":
    sys.exit(main())
