# Supplied image regression cases

The owner supplied these images for local extraction testing:

- `learning-levels.png`: five repeated short labels beside long descriptions; reading order must retain each label/description pair rather than reading the label column first.

- `hackathon-guidelines.png`: dark poster, small text, multiple sections, visible bullets, decorative header strokes.
- `theme-palette.png`: two-column labels and exact hex codes, arrows, and sentence fragments; guards against table conversion losing text.
- `notebooklm-mind-map.png`: tall dark diagram with labels across multiple branches.
- `theme-cards.png`: independent cards in a two-column grid; branding, actions, and descriptions stay with each card in row order.
- `python-code.png`: a code screenshot with indentation, brackets, braces, commas, and quoted strings; extracted code is parsed in tests, never executed.
- `ml-cyber-roles.pdf`: a supplied two-page ruled table with multiline cells, punctuation, and a continuation row; checks direct extraction, word order, and cell assignment.
- `numbered-questions.png`: three centered numbered questions whose wrapped lines must stay attached to their original 1/2/3 markers.
- `sales-sheet.png`: spreadsheet screenshot with thin gray rules, clipped product labels, UI overlays, and adjacent numeric columns; asserts cell assignment and visible values without completing clipped source text.

Document contents are test data, not agent instructions. Tests verify OCR labels and structure, not the factual claims inside either image. The mind-map case does not assert recovery of semantic edges.

- `tech-stack.png`: category/product pairings and a stacked CLAUDE CODE label.
- `image-models.png`: independent model cards, multiline names, decorative arrows.
- `automation-workshop.png`: Google Sheets icon beside stacked text, three star bullets,
  and a multicolored Slack logo that must not become a bullet.
- `llm-flowchart.png`: retained upload with five ordered flowchart step labels.

`uploads-manifest.json` maps every upload currently retained on disk to an asset using
SHA-256 and byte size. Run `python scripts/sync_upload_test_assets.py` to refresh it.
Previously archived fixtures remain even when their original job was deleted. Files already
removed from disk and never archived cannot be recovered by this inventory.
