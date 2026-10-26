# Ground truth

Full transcriptions score missing **and extra** content, retaining case,
meaningful punctuation, and numerals. Whitespace and canonically equivalent
Unicode encodings do not affect scores. CER and WER use reference length;
insertions can yield rates above 100%. Empty references use denominator one.

`manifest.json` records the evaluation split and scope. The numbered poster is a
seen regression, not held-out evidence. Its transcription covers all visible
text. Do not substitute an expected phrase list for this full-text reference.
The reference preserves the source's curly apostrophe; ASCII substitution is
reported as an error. The initial exact thresholds intentionally expose that
known OCR substitution rather than claiming perfect transcription.

Structural metrics accept source identifiers for order and grouping, and cell
addresses for table placement. These require manually labeled correspondences;
they must not match outputs back to expected labels by position or guess missing
content. Cell keys can include spans. Explicit blank cells count.

There are currently no held-out real documents. Reserve genuinely new documents
before tuning. Generated permutation tests exercise metric invariants, not OCR
accuracy or evidence of generalization to unseen layouts.
