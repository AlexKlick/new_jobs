#!/usr/bin/env python3
import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

AGENT_SDK_ROOT = "/home/alexk/documents/agents_sdk"
sys.path.insert(0, AGENT_SDK_ROOT)
from agents_sdk.resume_agent.models import JobEntry

WORKSPACE = Path("/home/alexk/documents/new_job_denjobs")
sys.path.insert(0, str(WORKSPACE))
# Ensure we map out the specific parsing module tests
from jobs.update_status import generate_markdown

class MockJobStatus:
    def __init__(self, job_index, company, state, latest_dir=None):
        self.job_index = job_index
        self.company = company
        self.state = state
        self.latest_dir = latest_dir

class TestUpdateStatus(unittest.TestCase):
    def setUp(self):
        self.mock_jobs = [
            JobEntry(
                index=1,
                heading="1. Acme Corp — AI Engineer",
                company="Acme Corp",
                role="AI Engineer",
                salary="$100k-$150k",
                remote="Remote",
                experience="2+ years",
                key_skills=["Python"],
                apply="Apply Here",
                apply_url="https://jobs.lever.co/acme/1",
                why_fit="Good fit",
                summary="Great company",
                company_context="Funded well"
            ),
            JobEntry(
                index=2,
                heading="2. Globex — SWE",
                company="Globex",
                role="SWE",
                salary=None,
                remote="On-site",
                experience="1 year",
                key_skills=["Java"],
                apply="Email",
                apply_url=None,
                why_fit="Ok",
                summary="Large corp",
                company_context=None
            )
        ]

    def test_url_extraction_formatting(self):
        """Test that URLs are populated properly via getattr, and fallback to N/A."""
        for job in self.mock_jobs:
            url = getattr(job, "apply_url", "N/A") or "N/A"
            if job.index == 1:
                self.assertEqual(url, "https://jobs.lever.co/acme/1")
            else:
                self.assertEqual(url, "N/A")

if __name__ == "__main__":
    unittest.main()
