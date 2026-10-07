import pytest

from it_toolbox.core.mbox_reader import MboxReader, decode_header_value, html_to_text


@pytest.fixture
def mbox_path(sample_mbox):
    return sample_mbox()


def test_index_reads_headers_in_file_order(mbox_path):
    reader = MboxReader(mbox_path)
    summaries = reader.index()

    assert [s.subject for s in summaries] == ["Server down", "Invoice", "Café news", "Disk alert", "No date"]
    assert summaries[0].sender == "alice@example.com"
    assert summaries[0].recipients == "ops@example.com"
    assert summaries[0].date_text == summaries[0].date.strftime("%Y-%m-%d %H:%M")
    assert [s.has_attachments for s in summaries] == [False, True, False, False, False]
    assert summaries[4].date is None
    assert summaries[4].date_text == ""


def test_dates_are_comparable_across_timezones(mbox_path):
    summaries = MboxReader(mbox_path).index()
    # tz-aware dates are normalized to naive local time so they sort together.
    assert summaries[0].date.tzinfo is None
    assert summaries[2].date > summaries[0].date


def test_summary_matches_headers_case_insensitively(mbox_path):
    summaries = MboxReader(mbox_path).index()

    assert summaries[0].matches("server")
    assert summaries[0].matches("alice@")
    assert summaries[0].matches("ops@example")
    assert not summaries[0].matches("invoice")


def test_load_returns_body_and_attachments(mbox_path):
    reader = MboxReader(mbox_path)
    keys = [s.key for s in reader.index()]

    detail = reader.load(keys[1])
    assert ("Subject", "Invoice") in detail.headers
    assert detail.text_body.strip() == "See attached."
    assert len(detail.attachments) == 1
    attachment = detail.attachments[0]
    assert (attachment.filename, attachment.content_type) == ("invoice.pdf", "application/pdf")
    assert attachment.size == len(b"%PDF-1.4 fake")
    assert reader.attachment_bytes(keys[1], 0) == b"%PDF-1.4 fake"


def test_load_html_only_message(mbox_path):
    reader = MboxReader(mbox_path)
    keys = [s.key for s in reader.index()]

    detail = reader.load(keys[2])
    assert detail.text_body is None
    assert "Hello &amp; welcome" in detail.html_body


def test_raw_bytes_is_the_stored_message(mbox_path):
    reader = MboxReader(mbox_path)
    key = reader.index()[0].key
    assert b"Subject: Server down" in reader.raw_bytes(key)


def test_search_bodies_matches_plain_and_html_text(mbox_path):
    reader = MboxReader(mbox_path)
    keys = [s.key for s in reader.index()]

    assert reader.search_bodies(keys, "UNREACHABLE") == {keys[0]}
    assert reader.search_bodies(keys, "hello & welcome") == {keys[2]}
    # Markup and stylesheets aren't searchable text.
    assert reader.search_bodies(keys, "color:red") == set()


def test_search_bodies_stops_when_cancelled(mbox_path):
    reader = MboxReader(mbox_path)
    keys = [s.key for s in reader.index()]
    assert reader.search_bodies(keys, "message", cancelled=lambda: True) is None


def test_missing_file_raises(tmp_path):
    with pytest.raises(FileNotFoundError):
        MboxReader(tmp_path / "nope.mbox")


def test_empty_file_has_no_messages(tmp_path):
    path = tmp_path / "empty.mbox"
    path.write_bytes(b"")
    assert MboxReader(path).index() == []


def test_decode_header_value_tolerates_garbage():
    assert decode_header_value(None) == ""
    assert decode_header_value("=?bogus-charset?q?x?=") != ""
    assert decode_header_value("multi\n  line") == "multi line"


def test_html_to_text():
    assert html_to_text("<script>x()</script><b>Hi</b>&nbsp;there") == "Hi there"


def test_scan_splits_messages_like_stdlib_mailbox(mbox_path):
    import mailbox

    reader = MboxReader(mbox_path)
    summaries = reader.index()
    box = mailbox.mbox(str(mbox_path), create=False)

    assert len(summaries) == len(box)
    for key, stdlib_key in zip((s.key for s in summaries), box.keys(), strict=True):
        assert reader.raw_bytes(key) == box.get_bytes(stdlib_key)


def test_crlf_files_are_read(tmp_path, mbox_path):
    crlf = tmp_path / "crlf.mbox"
    crlf.write_bytes(mbox_path.read_bytes().replace(b"\n", b"\r\n"))

    summaries = MboxReader(crlf).index()

    assert [s.subject for s in summaries][:2] == ["Server down", "Invoice"]
    assert summaries[1].has_attachments


def test_index_reports_scanning_then_reading_progress(mbox_path):
    from it_toolbox.core.mbox_reader import READING, SCANNING

    events = []
    MboxReader(mbox_path).index(progress=lambda *event: events.append(event))

    size = mbox_path.stat().st_size
    assert events[0][0] == SCANNING
    assert (SCANNING, size, size) in events
    reading = [e for e in events if e[0] == READING]
    assert reading[0] == (READING, 0, 5)
    assert reading[-1] == (READING, 5, 5)
    assert events.index((SCANNING, size, size)) < events.index(reading[0])


def test_index_can_be_cancelled(mbox_path):
    from it_toolbox.core.mbox_reader import IndexCancelled

    with pytest.raises(IndexCancelled):
        MboxReader(mbox_path).index(cancelled=lambda: True)
