# Internship documentation

Placement documentation for BUAD920 Internship (AIS, NZQF Level 9, 30 credits)
hosted by Wizards Learning Hub.

| File | Purpose |
|---|---|
| `BUAD920_Internship_Proposal_Shanika_Kirillawala.md` | Source of truth for the proposal. Edit this. |
| `BUAD920_Internship_Proposal_Shanika_Kirillawala.docx` | Submission copy for AIS, generated from the `.md`. |
| `md2docx.py` | Regenerates the `.docx` from the `.md`. |

Regenerate the Word version after editing the markdown:

```bash
python3 docs/internship/md2docx.py \
  docs/internship/BUAD920_Internship_Proposal_Shanika_Kirillawala.md \
  docs/internship/BUAD920_Internship_Proposal_Shanika_Kirillawala.docx
```

Requires `python-docx`. The generated file is schema-validated with
`.claude/skills/synced/docx/scripts/office/validate.py` where available.

Fields written as «like this» in the proposal are placeholders for the host
organisation to complete before signature — search for `«` before issuing.
