# Design QA — v0.6.0 login manager

Status: passed

## Reference target

- WinSCP Login Dialog screenshot from the user-provided WinSCP screenshots page.
- Compact native desktop hierarchy: saved sites/folders on the left, selected
  account editor on the right, and clear Login/management actions at the bottom.

## Required checks

- Startup presents the account manager before the transfer window.
- Saved accounts are grouped into folders and searchable.
- Selecting an account fills every connection field; double-click and Login connect.
- New, Save, Duplicate, rename/move, Delete, Import, Workspace, and Quick Connect work.
- Passwords remain outside profile JSON in the operating-system credential store.
- Main transfer window retains the compact connection strip for quick tests.
- Layout remains usable at its minimum size and labels/actions are not clipped.

## Verification result

- Captured the native KDE/Tk window at 820 x 500 with representative accounts
  grouped under Private and Work folders.
- The hierarchy, disclosure controls, editor fields, status guidance, and bottom
  action row are visible without clipping and closely follow the reference flow.
- Captured a clean empty-state launch separately; New site is selected and every
  required field and action remains available.
- Automated verification passed: Ruff lint/format, mypy, Bandit, and all 56 tests.
