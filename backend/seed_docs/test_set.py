"""Held-out test set with reference answers for evaluation baselines.

45 questions:
  - 10 per seed document (40 total, grounded in the corpus)
  -  5 out-of-scope adversarial questions where the correct answer is a refusal
    ("I don't have enough information...") — these test hallucination resistance.
"""

TEST_SET = [
    # -------------------- remote_work_policy.md (10) --------------------
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
        "question": "What performance rating must an employee hold to be eligible for remote work?",
        "reference": "'Meets Expectations' or higher on their most recent review.",
        "expected_source": "remote_work_policy.md",
    },
    {
        "question": "Which form must a manager sign to approve remote work?",
        "reference": "Form HR-RW-01.",
        "expected_source": "remote_work_policy.md",
    },
    {
        "question": "What is the minimum broadband requirement for a remote work location?",
        "reference": "At least 50 Mbps downstream and 10 Mbps upstream.",
        "expected_source": "remote_work_policy.md",
    },
    {
        "question": "What are the required core hours for remote employees?",
        "reference": "10:00 to 16:00 local time.",
        "expected_source": "remote_work_policy.md",
    },
    {
        "question": "Are cafes and other public networks approved locations for handling Confidential data?",
        "reference": "No, they are not approved for Confidential or Restricted data.",
        "expected_source": "remote_work_policy.md",
    },
    {
        "question": "Which VPN configuration profile must remote employees use to connect to internal systems?",
        "reference": "VPN-CORP-2024.",
        "expected_source": "remote_work_policy.md",
    },
    {
        "question": "How much notice is required to revoke remote work privileges for a policy violation?",
        "reference": "14 days notice.",
        "expected_source": "remote_work_policy.md",
    },
    {
        "question": "Under which expense category should ergonomic accessory reimbursements be filed?",
        "reference": "EXP-ERG-002.",
        "expected_source": "remote_work_policy.md",
    },

    # -------------------- data_retention_standard.md (10) --------------------
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
        "question": "What is the document ID for the data retention and classification standard?",
        "reference": "STD-SEC-007.",
        "expected_source": "data_retention_standard.md",
    },
    {
        "question": "How many data classification tiers does Acme use, and what are they?",
        "reference": "Four tiers: Public, Internal, Confidential, Restricted.",
        "expected_source": "data_retention_standard.md",
    },
    {
        "question": "How long must Restricted-tier data be retained?",
        "reference": "10 years from creation, stored in the Vault under STD-SEC-009.",
        "expected_source": "data_retention_standard.md",
    },
    {
        "question": "Which storage class is used for Confidential-tier data?",
        "reference": "Archive with WORM.",
        "expected_source": "data_retention_standard.md",
    },
    {
        "question": "Which tool is approved for cryptographic erasure of digital data?",
        "reference": "DEL-KEY-3, verified by two engineers.",
        "expected_source": "data_retention_standard.md",
    },
    {
        "question": "Which NIST standard governs physical drive destruction?",
        "reference": "NIST SP 800-88 Purge or Destroy.",
        "expected_source": "data_retention_standard.md",
    },
    {
        "question": "How often is retention compliance audited?",
        "reference": "Quarterly, with findings logged in ticket queue AUDIT-DR.",
        "expected_source": "data_retention_standard.md",
    },
    {
        "question": "What is the maximum validity period of a retention exception?",
        "reference": "At most 12 months; must be renewed after.",
        "expected_source": "data_retention_standard.md",
    },

    # -------------------- widget_3000_manual.md (10) --------------------
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
        "question": "What is the operating voltage range of the Widget-3000?",
        "reference": "24 V DC ±10%.",
        "expected_source": "widget_3000_manual.md",
    },
    {
        "question": "What is the peak current draw of the Widget-3000?",
        "reference": "3.5 A.",
        "expected_source": "widget_3000_manual.md",
    },
    {
        "question": "What does Widget-3000 fault code E02 mean and how is it recovered?",
        "reference": "E02 means firmware signature is invalid. Recover by reflashing with the WG3K-FW-RECOVERY image.",
        "expected_source": "widget_3000_manual.md",
    },
    {
        "question": "Approximately how long does a Widget-3000 firmware update take, and can power be removed during it?",
        "reference": "About 90 seconds; power must not be removed during the update.",
        "expected_source": "widget_3000_manual.md",
    },
    {
        "question": "What is the RS-485 configuration for the Widget-3000?",
        "reference": "115200 baud, 8N1.",
        "expected_source": "widget_3000_manual.md",
    },
    {
        "question": "What torque specification is required for terminal block TB-1?",
        "reference": "0.5 Nm.",
        "expected_source": "widget_3000_manual.md",
    },
    {
        "question": "What does a solid green STATUS LED indicate on the Widget-3000?",
        "reference": "READY — the application has started successfully.",
        "expected_source": "widget_3000_manual.md",
    },
    {
        "question": "How long may capacitors on the Widget-3000 retain charge after power is removed?",
        "reference": "Up to 60 seconds.",
        "expected_source": "widget_3000_manual.md",
    },

    # -------------------- incident_response_runbook.md (10) --------------------
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
    {
        "question": "What is the document ID of the incident response runbook?",
        "reference": "RUN-IR-001.",
        "expected_source": "incident_response_runbook.md",
    },
    {
        "question": "What is the response time for a SEV-2 incident?",
        "reference": "Within 1 hour.",
        "expected_source": "incident_response_runbook.md",
    },
    {
        "question": "Which team owns the Detect and Triage phases of an incident?",
        "reference": "The SOC (Security Operations Center).",
        "expected_source": "incident_response_runbook.md",
    },
    {
        "question": "Who must approve external SEV-1 communications?",
        "reference": "Legal.",
        "expected_source": "incident_response_runbook.md",
    },
    {
        "question": "Which EDR tool is used to isolate affected hosts during containment?",
        "reference": "Falcon Contain.",
        "expected_source": "incident_response_runbook.md",
    },
    {
        "question": "How frequently must internal status updates be posted during a SEV-1 incident?",
        "reference": "Every 30 minutes in the #ir-comms channel.",
        "expected_source": "incident_response_runbook.md",
    },
    {
        "question": "By when must the Incident Commander publish a post-mortem after resolution?",
        "reference": "Within 5 business days of resolution.",
        "expected_source": "incident_response_runbook.md",
    },
    {
        "question": "Which Jira project tracks incident-response action items?",
        "reference": "SEC-IR.",
        "expected_source": "incident_response_runbook.md",
    },

    # -------------------- Out-of-scope adversarial (5) --------------------
    # For these, the correct answer is a refusal — no invention allowed.
    {
        "question": "What is the CEO's annual salary at Acme Corp?",
        "reference": "The documents do not contain this information — the model should refuse.",
        "expected_source": "OUT_OF_SCOPE",
    },
    {
        "question": "What is the operating voltage of the Widget-4000?",
        "reference": "There is no Widget-4000 in the corpus — the model should refuse (only Widget-3000 exists).",
        "expected_source": "OUT_OF_SCOPE",
    },
    {
        "question": "Where is Acme Corp's global headquarters located?",
        "reference": "The documents do not contain this information — the model should refuse.",
        "expected_source": "OUT_OF_SCOPE",
    },
    {
        "question": "What is the maximum PTO allotment for a full-time employee at Acme?",
        "reference": "The documents do not contain PTO information — the model should refuse.",
        "expected_source": "OUT_OF_SCOPE",
    },
    {
        "question": "Which color is the Widget-3000 chassis painted?",
        "reference": "The manual does not describe chassis color — the model should refuse.",
        "expected_source": "OUT_OF_SCOPE",
    },
]
