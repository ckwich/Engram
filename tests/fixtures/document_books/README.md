# Document Book Fixture Manifests

These fixtures are synthetic manifests for Engram's Book Dismantling Gate.
They prove shape and provenance requirements without committing source books or
extracted copyrighted text.

Do not commit copyrighted PDFs, rendered page images, OCR text from books, or
derived long-form excerpts to this directory.

Required fixture ids:

- `clean_text_pdf`
- `book_style_pdf`
- `image_only_pdf`
- `table_heavy_page`
- `figure_caption_page`
- `rotated_page`
- `ocr_noise_page`

Optional local smoke tests can point `ENGRAM_DOCUMENT_FIXTURE_DIR` at a private
PDF corpus such as `C:\Path\To\Private\PdfCorpus`. Those runs are machine-local
and must skip cleanly when the directory or local PDF tools are unavailable.
