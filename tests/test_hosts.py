from fokus_rejimi.hosts import (MARK_END, MARK_START, SYSTEM_HOSTS, DryRunHosts, HostsManager, add_block, expand,
                                has_block, normalize_domain, strip_block)

ORIGINAL = "# sample hosts\r\n127.0.0.1 localhost\r\n10.0.0.5 nas.local\r\n"


def mgr(tmp_path):
    p = tmp_path / "hosts"
    p.write_bytes(ORIGINAL.encode())
    calls = []
    m = HostsManager(p, tmp_path / "bak", flush=lambda: calls.append(1))
    assert m.path != SYSTEM_HOSTS
    return m, p, calls


def test_normalize_domain():
    assert normalize_domain("https://www.YouTube.com/watch?v=1") == "youtube.com"
    assert normalize_domain("reddit.com:443") == "reddit.com"
    assert normalize_domain("not a domain") is None
    assert normalize_domain("localhost") is None
    assert expand(["x.com", "www.x.com", "bad"]) == ["x.com", "www.x.com"]


def test_apply_and_remove_restore_exactly(tmp_path):
    m, p, calls = mgr(tmp_path)
    n = m.apply(["youtube.com", "tiktok.com"])
    assert n == 4
    text = p.read_text()
    assert MARK_START in text and "0.0.0.0 www.youtube.com" in text and "127.0.0.1 localhost" in text
    assert m.is_blocked()
    assert len(list((tmp_path / "bak").glob("hosts.*.bak"))) == 1
    assert m.remove() is True
    assert p.read_bytes().decode() == ORIGINAL
    assert m.remove() is False
    assert len(calls) == 2


def test_reapply_replaces_block(tmp_path):
    m, p, _ = mgr(tmp_path)
    m.apply(["a.com"])
    m.apply(["b.com"])
    t = p.read_text()
    assert t.count(MARK_START) == 1 and "a.com" not in t and "b.com" in t


def test_strip_unfinished_block():
    broken = "127.0.0.1 localhost\n" + MARK_START + "\n0.0.0.0 x.com\n"
    assert strip_block(broken) == "127.0.0.1 localhost\n"
    assert has_block(add_block("", ["x.com"]))


def test_user_lines_after_block_survive(tmp_path):
    m, p, _ = mgr(tmp_path)
    m.apply(["x.com"])
    p.write_bytes(p.read_bytes() + b"192.168.1.2 printer\r\n")
    m.remove()
    t = p.read_text()
    assert "192.168.1.2 printer" in t and MARK_END not in t


def test_empty_list_does_nothing(tmp_path):
    m, p, _ = mgr(tmp_path)
    assert m.apply(["???"]) == 0
    assert p.read_bytes().decode() == ORIGINAL


def test_dry_run():
    d = DryRunHosts()
    d.apply(["x.com"])
    assert d.is_blocked() and d.remove() and not d.is_blocked()
