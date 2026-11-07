from __future__ import annotations
import json
import sqlite3
import pytest
from pid_reader.api import ReadParams, read_pid
from pid_reader.engineering.project import ProjectStore


def test_import_and_review_persist(synthetic_pdf,tmp_path):
    pdf=read_pid(synthetic_pdf,ReadParams())
    path=tmp_path/"project.sqlite"
    with ProjectStore(path) as store:
        eid=store.add_extraction(pdf,source_pdf_bytes=synthetic_pdf)
        assert store.get_source_pdf(pdf["document"]["sha256"])==synthetic_pdf
        assert store.add_extraction(pdf)==eid
        items=store.list_objects(text="V-101",object_class="VESSEL")
        assert len(items)==1
        oid=items[0]["observation_id"]
        assert store.get_object(oid)["text"]=="V-101"
        did=store.review(oid,actor="Engineer Test",decision="ACCEPTED_AS_READING",reason="Synthetic drawing")
        assert did.startswith("dec-")
        assert store.effective_review(oid)["decision"]=="ACCEPTED_AS_READING"
        with pytest.raises(sqlite3.DatabaseError):
            with store.db:store.db.execute("DELETE FROM observation WHERE observation_id=?",(oid,))
    with ProjectStore(path) as reopened:
        assert reopened.get_object(oid)["text"]=="V-101"
        assert reopened.effective_review(oid)["actor"]=="Engineer Test"


def test_human_review_guards(synthetic_pdf,tmp_path):
    data=read_pid(synthetic_pdf,ReadParams())
    with ProjectStore(tmp_path/"x.sqlite") as store:
        store.add_extraction(data)
        oid=store.list_objects()[0]["observation_id"]
        with pytest.raises(ValueError):store.review(oid,actor="",decision="ACCEPTED_AS_READING",reason="")
        with pytest.raises(ValueError):store.review(oid,actor="User",decision="EDITED_AND_ACCEPTED",reason="Reason")
        with pytest.raises(ValueError):store.review(oid,actor="User",decision="REJECTED",reason="No")
        store.review(oid,actor="User",decision="EDITED_AND_ACCEPTED",reason="Correct symbol interpretation",edited={"class":"OTHER"})
        assert store.effective_review(oid)["decision"]=="EDITED_AND_ACCEPTED"
        assert store.get_object(oid)["class"] != "OTHER"  # original observation remains unchanged


def test_import_rejects_tampering(synthetic_pdf,tmp_path):
    data=read_pid(synthetic_pdf,ReadParams())
    data["objects"][0]["text"]="tampered"
    with ProjectStore(tmp_path/"y.sqlite") as store:
        with pytest.raises(ValueError):store.add_extraction(data)
