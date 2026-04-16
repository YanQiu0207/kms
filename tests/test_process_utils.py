from __future__ import annotations

from scripts.process_utils import _parse_unix_ss_listeners, _parse_windows_netstat_listeners


def test_parse_windows_netstat_listeners():
    raw = """
  Proto  Local Address          Foreign Address        State           PID
  TCP    127.0.0.1:49153        0.0.0.0:0              LISTENING       56312
  TCP    127.0.0.1:8765         0.0.0.0:0              LISTENING       1200
"""
    assert _parse_windows_netstat_listeners(raw) == {49153: 56312, 8765: 1200}


def test_parse_unix_ss_listeners():
    raw = """
State  Recv-Q Send-Q Local Address:Port  Peer Address:PortProcess
LISTEN 0      2048   127.0.0.1:49153     0.0.0.0:*    users:(("python",pid=56312,fd=11))
LISTEN 0      4096   0.0.0.0:8000        0.0.0.0:*    users:(("uvicorn",pid=2200,fd=9))
"""
    assert _parse_unix_ss_listeners(raw) == {49153: 56312, 8000: 2200}
