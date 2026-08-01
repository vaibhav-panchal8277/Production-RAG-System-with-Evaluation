"""Held-out test set with reference answers for evaluation baselines."""

TEST_SET = [
    {
        "question": "What is the minimum tenure required for an employee to be eligible for remote work?",
        "reference": "Six (6) months of continuous employment.",
        "expected_source": "remote_work_policy.md",
    },
    {
        "question": "What is the annual reimbursement limit for ergonomic accessories under the remote work policy?",
        "reference": "USD 500 per calendar year (expense category EXP-ERG-002).",
        "expected_source": "remote_work_policy.md",
    },
    {
        "question": "How long must Confidential-tier data be retained?",
        "reference": "7 years from creation, stored in Archive with WORM.",
        "expected_source": "data_retention_standard.md",
    },
    {
        "question": "What is the approved shredder particle size for paper disposal?",
        "reference": "Cross-cut to 4mm x 15mm or smaller.",
        "expected_source": "data_retention_standard.md",
    },
    {
        "question": "What does fault code E03 on the Widget-3000 indicate and how should it be recovered?",
        "reference": "E03 means a config CRC error. Recover by restoring from CFG-B using `wg3k-cli restore`.",
        "expected_source": "widget_3000_manual.md",
    },
    {
        "question": "On which port does the Widget-3000 expose Modbus TCP?",
        "reference": "Port 502.",
        "expected_source": "widget_3000_manual.md",
    },
    {
        "question": "What is the target time-to-acknowledge for a SEV-1 security incident?",
        "reference": "Under 15 minutes.",
        "expected_source": "incident_response_runbook.md",
    },
    {
        "question": "Within how many hours must Acme notify regulators if customer PII is accessed in a SEV-1 incident?",
        "reference": "Within 72 hours, per policy POL-PRV-011.",
        "expected_source": "incident_response_runbook.md",
    },
]
