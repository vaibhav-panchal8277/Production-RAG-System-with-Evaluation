# Acme Corp Incident Response Runbook

## 1. Purpose
Runbook ID: RUN-IR-001. This runbook describes how the Security Operations team responds to
information-security incidents affecting Acme Corp systems, customers, or data.

## 2. Severity Levels
- **SEV-1**: Active data breach, ransomware in production, or customer-facing outage caused by
  a security event. Response begins immediately, target time-to-acknowledge under 15 minutes.
- **SEV-2**: Confirmed compromise limited to non-production; suspected data exfiltration.
  Response within 1 hour.
- **SEV-3**: Suspicious activity requiring investigation but no confirmed impact. Response
  within 1 business day.

## 3. Response Phases
Every incident follows the phases: Detect, Triage, Contain, Eradicate, Recover, Learn.
Detect and Triage are owned by the SOC. Contain onward involves the Incident Commander (IC).

## 4. Roles
- **Incident Commander (IC)**: on-call security engineer, coordinates the response.
- **Communications Lead**: drafts internal and external updates, approved by Legal for SEV-1.
- **Scribe**: maintains the timeline in the incident channel #ir-<incident-id>.

## 5. Containment Actions
Depending on the vector, containment may include:
- Revoking OAuth tokens and rotating service account keys via KMS runbook KMS-ROT-04.
- Isolating affected hosts using EDR tool "Falcon Contain".
- Blocking indicators of compromise (IOCs) at the perimeter firewall (change ticket FW-CHG).

## 6. Communications
SEV-1 incidents require:
- Internal status update every 30 minutes in the #ir-comms channel.
- Executive briefing within 2 hours of declaration.
- Regulatory notification within 72 hours if customer PII was accessed, per policy POL-PRV-011.

## 7. Post-Incident
Within 5 business days of resolution, the IC publishes a blameless post-mortem containing:
- Timeline
- Root cause
- Detection gap analysis
- Action items with owners and due dates
Action items are tracked in Jira project SEC-IR.
