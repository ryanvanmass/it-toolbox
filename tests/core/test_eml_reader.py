import pytest

from it_toolbox.core.eml_reader import EmlReader


def test_reads_headers_body_and_attachments(sample_eml):
    reader = EmlReader(sample_eml())

    detail = reader.load()

    assert dict(detail.headers)["Subject"] == "Invoice"
    assert dict(detail.headers)["From"] == "billing@example.com"
    assert detail.text_body.strip() == "See attached."
    assert [(a.filename, a.content_type) for a in detail.attachments] == [
        ("invoice.pdf", "application/pdf")
    ]
    assert reader.attachment_bytes(0) == b"%PDF-1.4 fake"


def test_crlf_line_endings(sample_eml):
    path = sample_eml()
    path.write_bytes(path.read_bytes().replace(b"\n", b"\r\n"))

    detail = EmlReader(path).load()

    assert dict(detail.headers)["Subject"] == "Invoice"
    assert detail.text_body.strip() == "See attached."


def test_leading_mbox_separator_line_is_skipped(sample_eml):
    path = sample_eml()
    path.write_bytes(b"From billing@example.com Sun Oct  5 08:00:00 2026\n" + path.read_bytes())

    detail = EmlReader(path).load()

    assert dict(detail.headers)["Subject"] == "Invoice"
    assert len(detail.attachments) == 1


def test_missing_file(tmp_path):
    with pytest.raises(FileNotFoundError):
        EmlReader(tmp_path / "gone.eml")


def test_empty_file(tmp_path):
    path = tmp_path / "empty.eml"
    path.write_bytes(b"\n")

    with pytest.raises(ValueError):
        EmlReader(path)
