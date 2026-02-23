#!/usr/bin/env python3
"""One-time helper to generate a minimal valid PDF fixture."""
import os

pdf = (
    b"%PDF-1.4\n"
    b"1 0 obj<</Type/Catalog/Pages 2 0 R>>endobj\n"
    b"2 0 obj<</Type/Pages/Kids[3 0 R]/Count 1>>endobj\n"
    b"3 0 obj<</Type/Page/MediaBox[0 0 612 792]/Parent 2 0 R/Resources<<>>>>endobj\n"
    b"xref\n"
    b"0 4\n"
    b"0000000000 65535 f \n"
    b"0000000009 00000 n \n"
    b"0000000058 00000 n \n"
    b"0000000115 00000 n \n"
    b"trailer<</Size 4/Root 1 0 R>>\n"
    b"startxref\n"
    b"192\n"
    b"%%EOF\n"
)

out = os.path.join(os.path.dirname(__file__), "sample.pdf")
with open(out, "wb") as f:
    f.write(pdf)
print(f"Written: {out} ({len(pdf)} bytes)")
