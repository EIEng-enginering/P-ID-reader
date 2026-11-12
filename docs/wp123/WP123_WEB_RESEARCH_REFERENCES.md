# Online technology references reviewed for WP01–WP03

These are research references, not proof that an optional model is installed or licence approved.

- PaddleOCR official repository: https://github.com/PaddlePaddle/PaddleOCR (current offline OCR model/pipeline options, subject to version, model licence and Windows CPU testing).
- PaddleOCR official OCR pipeline: https://www.paddleocr.ai/main/en/version3.x/pipeline_usage/OCR.html (model interface; the Python package was **not** installed in this deliverable).
- SAHI sliced inference: https://github.com/obss/sahi (large-image tiled detections; model and weight licences independent of SAHI's licence).
- Tesseract repository: https://github.com/tesseract-ocr/tesseract (existing offline OCR path, used in the tested optional region OCR).
- OpenCV documentation: https://docs.opencv.org/4.x/ (Hough circle proposals and geometric filtering, not a semantic valve/instrument classifier).

Technical decisions: avoid network downloads or training at runtime; re-use supplied Windows E5 model detections as **unverified** source observations. No generic trained plant symbol classifier or model weights were added. This protects licence and provenance gates. The WP01–03 implementation must be assessed with independently labelled S418/P&IDs, not model-reported confidence as an accuracy percentage.
