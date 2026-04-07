import sys
import os
import uuid
import json
from datetime import datetime, timezone

# Add the project root to sys.path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), ".")))

from search.search_store import SearchStore, JobSource, SearchRunStatus
from research.research_store import get_research_store, compute_company_key

def main():
    store = SearchStore()
    research_store = get_research_store()
    
    # 1. Ensure companies and research data exist
    companies = [
        {"name": "Google", "key": "google", "sentiment": 0.8, "claims": 5, "questions": 3},
        {"name": "Netflix", "key": "netflix", "sentiment": 0.2, "claims": 2, "questions": 1},
        {"name": "Amazon", "key": "amazon", "sentiment": -0.1, "claims": 10, "questions": 5},
    ]
    
    for comp in companies:
        research_store.ensure_company(comp["key"], comp["name"])
        snap = research_store.create_snapshot(comp["key"], source_count=1)
        
        # Add a dummy claim to trigger sentiment summarizing
        research_store.add_claim(
            snapshot_id=snap.snapshot_id,
            company_key=comp["key"],
            claim_text=f"Great company culture at {comp['name']}",
            source_url="https://glassdoor.com",
            collected_at=datetime.now(timezone.utc).isoformat(),
            sentiment_score=comp["sentiment"]
        )
        # Add dummy interview questions
        for i in range(comp["questions"]):
             research_store.add_interview_question(
                snapshot_id=snap.snapshot_id,
                company_key=comp["key"],
                question_text=f"Question {i+1} for {comp['name']}",
                source_url="https://glassdoor.com",
                collected_at=datetime.now(timezone.utc).isoformat(),
            )
        
        research_store.complete_snapshot(snap.snapshot_id, claim_count=comp["claims"], question_count=comp["questions"])

    # 2. Create a search run
    run = store.create_run(preference_id=None, preference_label="QA Manual Injection")
    
    # 3. Add candidates
    candidates_data = [
        {
            "company": "Google",
            "role": "Senior AI Engineer",
            "location": "Denver, CO",
            "salary": "$180k-$250k",
            "remote": "hybrid",
            "posted_date": "2024-03-01",
            "source": JobSource.career_page,
            "source_url": "https://google.com/jobs/1",
            "apply_url": "https://google.com/jobs/1/apply",
            "extraction_method": "page parse",
            "source_confidence": "high",
            "search_rank": 1,
        },
        {
            "company": "Netflix",
            "role": "Python Developer",
            "location": "Remote",
            "salary": "$200k",
            "remote": "remote",
            "posted_date": "2024-03-02",
            "source": JobSource.generic_web,
            "source_url": "https://linkedin.com/jobs/2",
            "apply_url": "https://netflix.com/jobs/2/apply",
            "extraction_method": "Claude",
            "source_confidence": "medium",
            "search_rank": 2,
        },
         {
            "company": "Amazon",
            "role": "Software Engineer",
            "location": "Seattle, WA",
            "salary": "$150k",
            "remote": "onsite",
            "posted_date": "2024-03-03",
            "source": JobSource.lever,
            "source_url": "https://lever.co/amazon/3",
            "apply_url": "https://lever.co/amazon/3/apply",
            "extraction_method": "ats_api",
            "source_confidence": "high",
            "search_rank": 3,
        }
    ]
    
    for cand in candidates_data:
        store.add_candidate(
            run_id=run.run_id,
            **cand
        )
    
    # 4. Update run status and counts
    total, new, dup = store.compute_run_counts(run.run_id)
    store.update_run_counts(run.run_id, total, new, dup)
    store.update_run_status(run.run_id, "completed")
    
    # 5. Create a list for this run
    lst = store.create_list_for_run(run.run_id, "QA Curated List")
    store.add_candidates_to_list_from_run(run.run_id)
    
    print(f"Successfully injected Run {run.run_id} and List {lst.list_id}")

if __name__ == "__main__":
    main()
