"""R5 update: the new code never opens a network connection (in-process guard; an OS-level deny/monitor is a separate Windows gate)."""
from __future__ import annotations

import socket
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent))
from test_r5_dexpi import make_snapshot  # noqa: E402

from pid_reader.engineering import connection_review as cr  # noqa: E402
from pid_reader.engineering import dexpi_proposed as dp  # noqa: E402
from pid_reader.formats import page_provenance as pp  # noqa: E402


def test_new_modules_make_no_network_call(monkeypatch, tmp_path):
    def boom(*a, **k):
        raise AssertionError("network access attempted")
    monkeypatch.setattr(socket.socket, "connect", boom)
    monkeypatch.setattr(socket, "create_connection", boom)
    monkeypatch.setattr(socket, "getaddrinfo", boom)
    res = dp.export_dexpi_proposed(make_snapshot(), tmp_path, mode="on")
    assert res["checks"]["readback"] == "PASS"
    assert cr.build_ledger([], "a" * 64)["entries"] == []
    assert pp.read_pdf_provenance(b"junk")["status"] == "UNREADABLE"
    # the official XSD / model files are only ever read from a path the caller supplies; there is no URL fetch in the writer
    src = Path(dp.__file__).read_text(encoding="utf-8")
    assert "urlopen" not in src and "requests" not in src and "http.client" not in src


def test_import_xml_namespaces_are_labels_not_fetched():
    xml, _ = dp.to_dexpi(make_snapshot())
    assert 'source="https://data.dexpi.org/models/2.0.1/Core.xml"' in xml                  # an identifier string in the file
    objs, issues = dp.audit_read(xml)
    assert issues == []                                                                       # reading it never resolves it
