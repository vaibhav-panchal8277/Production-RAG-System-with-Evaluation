# Acme Corp Data Retention & Classification Standard

## 1. Overview
Document ID: STD-SEC-007. This standard defines data classification tiers, retention windows,
and disposal requirements for all information handled by Acme Corp systems and personnel.

## 2. Data Classification Tiers
Acme uses four tiers:
- **Public**: Marketing materials, published documentation. No restriction.
- **Internal**: Business-as-usual content shared inside Acme. Not for external distribution.
- **Confidential**: Customer PII, contracts, financial statements, employee records. Requires
  access control lists and encryption at rest.
- **Restricted**: Trade secrets, security keys, payment card data (PCI scope), unreleased
  financial results. Handled under standard STD-SEC-009 with dual-control access.

## 3. Retention Windows
Default retention windows per tier:
| Tier          | Retention                | Storage Class      |
|---------------|--------------------------|--------------------|
| Public        | Indefinite               | Standard           |
| Internal      | 5 years from last access | Standard / Archive |
| Confidential  | 7 years from creation    | Archive with WORM  |
| Restricted    | 10 years from creation   | Vault (STD-SEC-009)|

Legal holds override standard retention and are set via Form LGL-HOLD-002.

## 4. Disposal
When data reaches its retention limit, it must be disposed of using an approved method:
- Digital: cryptographic erasure using tool DEL-KEY-3, verified by two engineers.
- Physical (paper): cross-cut shredding to particle size 4mm x 15mm or smaller.
- Physical (drives): NIST SP 800-88 Purge or Destroy, with a signed certificate of destruction.

## 5. Roles
- **Data Owner**: business owner of the dataset, approves access requests.
- **Data Custodian**: IT team that implements controls.
- **Privacy Officer**: reviews all Restricted-tier exceptions.

## 6. Audit
Retention compliance is audited quarterly. Findings are logged in ticket queue AUDIT-DR and
must be remediated within 30 days for Confidential and 7 days for Restricted findings.

## 7. Exceptions
Exceptions must be requested using Form STD-SEC-007-EX and approved by both the Data Owner
and the Privacy Officer. Exceptions are valid for at most 12 months and must be renewed.
