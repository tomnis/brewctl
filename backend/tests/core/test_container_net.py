import pytest

from brewctl.core.container_net import (
    apply_container_networking,
    parse_extra_hosts,
)


def test_parse_extra_hosts_single():
    assert parse_extra_hosts("service.internal:192.0.2.10") == [
        ("service.internal", "192.0.2.10"),
    ]


def test_parse_extra_hosts_multiple_and_spaces():
    assert parse_extra_hosts("a.local:1.2.3.4, b.local:5.6.7.8") == [
        ("a.local", "1.2.3.4"),
        ("b.local", "5.6.7.8"),
    ]


@pytest.mark.parametrize("bad", ["nocolon", "host:", ":1.2.3.4", "h:x:y", "bad host:1.2.3.4"])
def test_parse_extra_hosts_rejects_malformed(bad):
    with pytest.raises(ValueError):
        parse_extra_hosts(bad)


def test_dns_appended_when_absent(tmp_path):
    resolv = tmp_path / "resolv.conf"
    resolv.write_text("search lan\n")
    apply_container_networking(dns="192.0.2.53", resolv_conf=resolv)
    assert "nameserver 192.0.2.53\n" in resolv.read_text()


def test_dns_appended_after_missing_trailing_newline(tmp_path):
    resolv = tmp_path / "resolv.conf"
    resolv.write_text("search lan")  # hand-edited files may lack the final newline
    apply_container_networking(dns="192.0.2.53", resolv_conf=resolv)
    text = resolv.read_text()
    assert "search lan\nnameserver 192.0.2.53\n" in text


def test_dns_not_duplicated(tmp_path):
    resolv = tmp_path / "resolv.conf"
    resolv.write_text("nameserver 192.0.2.53\n")
    apply_container_networking(dns="192.0.2.53", resolv_conf=resolv)
    assert resolv.read_text().count("nameserver 192.0.2.53") == 1


def test_dns_dedup_ignores_whitespace_variants(tmp_path):
    resolv = tmp_path / "resolv.conf"
    resolv.write_text("nameserver  192.0.2.53\n")
    apply_container_networking(dns="192.0.2.53", resolv_conf=resolv)
    lines = [l for l in resolv.read_text().splitlines() if l.strip() == "nameserver 192.0.2.53"]
    assert len(lines) == 1


def test_extra_hosts_appended(tmp_path):
    hosts = tmp_path / "hosts"
    hosts.write_text("127.0.0.1 localhost\n")
    apply_container_networking(
        extra_hosts=[("service.internal", "192.0.2.10")], hosts_file=hosts
    )
    text = hosts.read_text()
    assert "192.0.2.10\tservice.internal\n" in text


def test_extra_hosts_idempotent(tmp_path):
    hosts = tmp_path / "hosts"
    line = "192.0.2.10\tservice.internal\n"
    hosts.write_text("127.0.0.1 localhost\n" + line)
    apply_container_networking(
        extra_hosts=[("service.internal", "192.0.2.10")], hosts_file=hosts
    )
    assert hosts.read_text().count(line) == 1


def test_noop_without_values(tmp_path):
    resolv = tmp_path / "resolv.conf"
    hosts = tmp_path / "hosts"
    apply_container_networking(resolv_conf=resolv, hosts_file=hosts)  # neither exists yet
    assert not resolv.exists() and not hosts.exists()


def test_dns_requires_valid_ip():
    with pytest.raises(ValueError):
        apply_container_networking(dns="not-an-ip", resolv_conf=None, hosts_file=None)
