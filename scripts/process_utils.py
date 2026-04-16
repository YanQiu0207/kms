from __future__ import annotations

import os
import signal
import subprocess

if os.name == "nt":
    import ctypes
    from ctypes import wintypes

    _KERNEL32 = ctypes.WinDLL("kernel32", use_last_error=True)
    _PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
    _PROCESS_TERMINATE = 0x0001
    _SYNCHRONIZE = 0x00100000
    _STILL_ACTIVE = 259
    _ERROR_ACCESS_DENIED = 5
    _ERROR_INVALID_PARAMETER = 87

    _KERNEL32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    _KERNEL32.OpenProcess.restype = wintypes.HANDLE
    _KERNEL32.GetExitCodeProcess.argtypes = [wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD)]
    _KERNEL32.GetExitCodeProcess.restype = wintypes.BOOL
    _KERNEL32.TerminateProcess.argtypes = [wintypes.HANDLE, wintypes.UINT]
    _KERNEL32.TerminateProcess.restype = wintypes.BOOL
    _KERNEL32.CloseHandle.argtypes = [wintypes.HANDLE]
    _KERNEL32.CloseHandle.restype = wintypes.BOOL


def pid_exists(pid: int) -> bool:
    if pid <= 0:
        return False

    if os.name != "nt":
        try:
            os.kill(pid, 0)
        except OSError:
            return False
        return True

    handle = _KERNEL32.OpenProcess(_PROCESS_QUERY_LIMITED_INFORMATION | _SYNCHRONIZE, False, pid)
    if not handle:
        last_error = ctypes.get_last_error()
        if last_error == _ERROR_ACCESS_DENIED:
            return True
        if last_error == _ERROR_INVALID_PARAMETER:
            return False
        return False

    try:
        exit_code = wintypes.DWORD()
        if not _KERNEL32.GetExitCodeProcess(handle, ctypes.byref(exit_code)):
            return True
        return exit_code.value == _STILL_ACTIVE
    finally:
        _KERNEL32.CloseHandle(handle)


def request_stop(pid: int) -> str:
    if os.name != "nt":
        os.kill(pid, signal.SIGTERM)
        return "graceful"

    # Try CTRL_BREAK first (graceful for processes in the same console group).
    try:
        os.kill(pid, signal.CTRL_BREAK_EVENT)
        return "graceful"
    except Exception:
        pass

    # CPython's os.kill on Windows uses OpenProcess(PROCESS_ALL_ACCESS, ...) which
    # can be denied for background processes started outside this console.
    # Try TerminateProcess with the minimal PROCESS_TERMINATE access right first.
    handle = _KERNEL32.OpenProcess(_PROCESS_TERMINATE, False, pid)
    if handle:
        try:
            if _KERNEL32.TerminateProcess(handle, 1):
                return "forced"
        finally:
            _KERNEL32.CloseHandle(handle)

    # Fall back to taskkill /F which enables SeDebugPrivilege internally and can
    # terminate elevated or SYSTEM processes from an admin context.
    result = subprocess.run(
        ["taskkill", "/F", "/PID", str(pid)],
        capture_output=True, text=True, check=False,
    )
    if result.returncode == 0:
        return "forced"
    raise OSError(
        f"taskkill /F /PID {pid} failed (rc={result.returncode}): "
        f"{result.stderr.strip() or result.stdout.strip()}"
    )


def _parse_windows_netstat_listeners(raw: str) -> dict[int, int]:
    listeners: dict[int, int] = {}
    for line in raw.splitlines():
        parts = line.split()
        if len(parts) < 5 or parts[0].upper() != "TCP" or parts[3].upper() != "LISTENING":
            continue
        local_address = parts[1]
        pid_text = parts[4]
        try:
            port = int(local_address.rsplit(":", 1)[1])
            pid = int(pid_text)
        except (IndexError, ValueError):
            continue
        listeners[port] = pid
    return listeners


def _parse_unix_ss_listeners(raw: str) -> dict[int, int]:
    listeners: dict[int, int] = {}
    for line in raw.splitlines():
        parts = line.split()
        if len(parts) < 6:
            continue
        local_address = parts[3]
        process_info = " ".join(parts[5:])
        if "pid=" not in process_info:
            continue
        try:
            port = int(local_address.rsplit(":", 1)[1])
            pid = int(process_info.split("pid=", 1)[1].split(",", 1)[0].rstrip(")"))
        except (IndexError, ValueError):
            continue
        listeners[port] = pid
    return listeners


def find_listening_pid(port: int) -> int | None:
    if port <= 0:
        return None

    if os.name == "nt":
        completed = subprocess.run(
            ["netstat", "-ano", "-p", "tcp"],
            capture_output=True,
            text=True,
            check=False,
        )
        if completed.returncode != 0:
            return None
        return _parse_windows_netstat_listeners(completed.stdout).get(port)

    completed = subprocess.run(
        ["ss", "-ltnp"],
        capture_output=True,
        text=True,
        check=False,
    )
    if completed.returncode != 0:
        return None
    return _parse_unix_ss_listeners(completed.stdout).get(port)
