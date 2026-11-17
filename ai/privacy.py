import csv
from functools import lru_cache
import ipaddress
import os
import re
import subprocess
from urllib.parse import urlsplit

from ai.client import LLMError


def endpoint_kind(url):
    host = urlsplit(url).hostname or ""
    if host == "localhost" or host.endswith(".localhost"):
        return "local"
    try:
        address = ipaddress.ip_address(host)
        return "local" if address.is_loopback or address.is_private else "remote"
    except ValueError:
        return "remote"


def contains_sensitive(value, secrets, depth=0):
    if depth > 32:
        return True
    if isinstance(value, str):
        return any(secret and secret in value for secret in secrets)
    if isinstance(value, dict):
        return any(contains_sensitive(key, secrets, depth + 1) or contains_sensitive(item, secrets, depth + 1) for key, item in value.items())
    if isinstance(value, list):
        return any(contains_sensitive(item, secrets, depth + 1) for item in value)
    return False


def redact(value, secrets=(), depth=0):
    if depth > 32:
        return "[redacted]"
    if isinstance(value, dict):
        return {key: "[redacted]" if key.casefold() in ("api_key", "authorization", "password", "token")
                else redact(item, secrets, depth + 1) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [redact(item, secrets, depth + 1) for item in value]
    if isinstance(value, str):
        value = re.sub(r"\\u([0-9a-fA-F]{4})", lambda match: chr(int(match.group(1), 16)), value)
        value = "".join("\ufffd" if 0xD800 <= ord(character) <= 0xDFFF else character for character in value)
        for secret in sorted((item for item in secrets if item), key=len, reverse=True):
            value = value.replace(secret, "[redacted]")
        value = re.sub(r"(?i)\bBearer\s+[^\s\"<>]+", "Bearer [redacted]", value)
        return re.sub(r"https?://[^\s\"<>]+", "[endpoint]", value)
    return value


@lru_cache(maxsize=1)
def _user_sid():
    result = subprocess.run(["whoami", "/user", "/fo", "csv", "/nh"], capture_output=True, text=True, check=True, timeout=5)
    sid = next(csv.reader(result.stdout.splitlines()))[-1]
    if not re.fullmatch(r"S-1-[0-9-]+", sid):
        raise ValueError("invalid identity")
    return sid


def secure_path(path, *, directory=False):
    try:
        if os.name != "nt":
            path.chmod(0o700 if directory else 0o600)
            return
        import ctypes
        from ctypes import wintypes

        security = ctypes.WinDLL("advapi32", use_last_error=True)
        kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        security.ConvertStringSecurityDescriptorToSecurityDescriptorW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, ctypes.POINTER(ctypes.c_void_p), ctypes.c_void_p]
        security.ConvertStringSecurityDescriptorToSecurityDescriptorW.restype = wintypes.BOOL
        security.SetFileSecurityW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, ctypes.c_void_p]
        security.SetFileSecurityW.restype = wintypes.BOOL
        kernel.LocalFree.argtypes = [ctypes.c_void_p]
        kernel.LocalFree.restype = ctypes.c_void_p
        inheritance = "OICI" if directory else ""
        descriptor = ctypes.c_void_p()
        sddl = f"D:P(A;{inheritance};FA;;;{_user_sid()})(A;{inheritance};FA;;;SY)"
        if not security.ConvertStringSecurityDescriptorToSecurityDescriptorW(sddl, 1, ctypes.byref(descriptor), None):
            raise OSError("descriptor")
        try:
            if not security.SetFileSecurityW(str(path), 0x80000004, descriptor):
                raise OSError("permissions")
        finally:
            kernel.LocalFree(descriptor)
    except (OSError, ValueError, subprocess.SubprocessError):
        raise LLMError("AI_LLM_CONFIG", field="private_file_permissions") from None