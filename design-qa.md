# Design QA — WinSCP-style dark dual-pane interface

Status: passed

## Evidence

- Main reference: `C:/Users/2e0lx/AppData/Local/Temp/codex-clipboard-eb8f8ba9-ab57-4eb6-8cf7-66444e99fb8a.png` (1149 × 701).
- Login reference: `C:/Users/2e0lx/AppData/Local/Temp/codex-clipboard-b62bd6ad-8ba6-4472-b4a9-46301a1257eb.png` (1149 × 701, including the 639 × 416 login dialog).
- Main implementation: `screenshots/debscp-main-v061-dark.png` (1182 × 792, native Windows capture at 100% density).
- Login implementation: `screenshots/debscp-login-v061-dark.png` (822 × 552, native Windows capture at 100% density).
- Main side-by-side comparison: `screenshots/design-qa-main-v061-comparison.png`.
- Login side-by-side comparison: `screenshots/design-qa-login-v061-comparison.png`.

The inspected states were the startup saved-account manager and the disconnected main workspace opened with Quick Connect. Both are complete native-window captures rather than cropped component renders.

## Fidelity review

- Fonts: compact Segoe UI typography on Windows with Linux-safe DejaVu Sans fallback; hierarchy and density are consistent with the reference.
- Layout and spacing: the application uses the reference's menu, connection toolbar, compact tab strip, matched local/remote toolbars, path controls, equal-width file panes, pane totals, and bottom status area. The login manager retains the reference's site list/editor split while accommodating the newer account and folder controls.
- Colour: dark charcoal surfaces, near-black file lists, cool grey borders, blue section labels, selected-row blue, and restrained status styling match the requested visual direction.
- Assets: DebSCP intentionally does not copy WinSCP branding or proprietary toolbar artwork. Clear text controls preserve every action without ambiguous substitute icons.
- Copy and content: protocol, host, port, username, password, remote folder, private key, saved-account management, import, Login, Quick Connect, transfer controls, and update controls are all present.
- Interactions and accessibility: visible focus/selection states remain intact; the account tree scrolls; lists have scrollbars; form labels are explicit; the main window has a 900 × 580 minimum; and the queue expands automatically when transfers create progress.

## Comparison history

1. Removed the notebook's oversized empty content strip so only the compact tab bar remains.
2. Collapsed the transfer queue by default and made it appear automatically when transfer activity begins.
3. Rebalanced the login form so host and account fields receive useful width while port and browse controls remain compact.
4. Re-captured the final v0.7.0 saved-account manager and main workspace and compared both against the supplied WinSCP references. No P0, P1, or P2 visual issue remains.

Intentional differences are the DebSCP identity, platform-native window chrome, the richer saved-account/folder controls, and an empty remote pane until a real connection is established.

## Verification

- Automated verification: Ruff formatting/lint, mypy, Bandit, 58 tests, package build, and whitespace checks.
- Final result: passed
