"""Text-layer proxy data is TRAIN-only, declared as such, and never counts as human-reviewed."""
import hashlib
import json

import pytest
from PIL import Image

from pid_reader.engineering.longterm import data as D
from pid_reader.engineering.longterm import readiness as R


def dataset(tmp_path, rows):
    out = tmp_path / "ds"
    out.mkdir(exist_ok=True)
    for r in rows:
        im = Image.new("L", (40, 12), 255)
        im.save(out / r["image_path"])
        r["image_sha256"] = D.sha(out / r["image_path"])
    (out / "dataset.json").write_text(json.dumps(dict(schema="pid-longterm-crops-v1", items=rows)))
    return out / "dataset.json"


def proxy_row(tmp_path, i=0, **kw):
    src = tmp_path / "s.pdf"
    src.write_bytes(b"%PDF-1 text layer")
    row = dict(id=f"p{i}", split="TRAIN", family_id="F1", source_sha256=hashlib.sha256(src.read_bytes()).hexdigest(), origin="VECTOR_TEXT_LAYER",
               review_status="EXACT_FROM_DOCUMENT_TEXT_LAYER", text=f"GHS-{i}", image_path=f"c{i}.png", source_path=str(src), page=1,
               bbox=dict(x0=.1, y0=.1, x1=.2, y1=.15), coordinate_frame="MEDIA_NORMALIZED_TOP_LEFT")
    row.update(kw)
    return row


def test_text_layer_proxy_is_accepted_for_training(tmp_path):
    rows, _ = D.validate(dataset(tmp_path, [proxy_row(tmp_path)]), purpose="train")
    assert rows[0]["origin"] == "VECTOR_TEXT_LAYER"


def test_text_layer_proxy_can_never_be_validation(tmp_path):
    with pytest.raises(ValueError, match="TRAIN"):
        D.validate(dataset(tmp_path, [proxy_row(tmp_path, split="VALIDATION")]), purpose="validate")


def test_provenance_must_be_declared_and_source_bytes_checked(tmp_path):
    with pytest.raises(ValueError, match="provenance"):
        D.validate(dataset(tmp_path, [proxy_row(tmp_path, review_status="VERIFIED_DEVELOPMENT")]))
    with pytest.raises(ValueError, match="Source drawing"):
        D.validate(dataset(tmp_path, [proxy_row(tmp_path, source_sha256="0" * 64)]))


def test_heldout_proxy_split_cannot_be_loaded_by_the_programme(tmp_path):
    with pytest.raises(ValueError):
        D.validate(dataset(tmp_path, [proxy_row(tmp_path, split="PROXY_HELDOUT")]))


def test_proxy_items_do_not_satisfy_the_reviewed_corpus_gate(tmp_path):
    train = dataset(tmp_path, [proxy_row(tmp_path, i) for i in range(60)])
    cfg = dict(train_dataset=str(train), validation_dataset=str(train))
    out = R.check_corpus(cfg)
    assert out["status"] == "FAIL"
