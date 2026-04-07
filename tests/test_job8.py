import asyncio
import json
from pathlib import Path
from agents_sdk.resume_agent.models import resolve_workspace
from agents_sdk.resume_agent.jobs_parser import parse_jobs_markdown, select_job
from agents_sdk.resume_agent.fact_store import load_fact_bundle, fact_yaml_path
from agents_sdk.resume_agent.generator import _generation_prompt, _query_json_with_fallback, _provider_enum

async def main():
    workspace = resolve_workspace(Path("/home/alexk/documents/new_job_denjobs"))
    jobs = parse_jobs_markdown(workspace / "jobs.md")
    job = next(j for j in jobs if j.index == 8)
    bundle = load_fact_bundle(fact_yaml_path(workspace))
    
    prompt = _generation_prompt(bundle, job, True)
    print("PROMPT LENGTH:", len(prompt))
    
    with open("/tmp/job8_prompt.txt", "w") as f:
        f.write(prompt)
    print("Wrote prompt to /tmp/job8_prompt.txt")

    print("Running query...")
    try:
        draft_payload, _, _, _ = await _query_json_with_fallback(
            prompt=prompt,
            primary=_provider_enum("zai"),
            fallback=None,
            cwd=workspace,
            max_turns=1,
        )
        print("SUCCESS!")
    except Exception as e:
        print("ERROR:", e)

if __name__ == "__main__":
    asyncio.run(main())
