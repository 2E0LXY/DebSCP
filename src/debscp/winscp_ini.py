from __future__ import annotations

import configparser
import re
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath
from urllib.parse import unquote_to_bytes

from .models import SessionConfig, default_port, normalize_remote_path

_PROTOCOLS = {0: "scp", 1: "sftp", 2: "sftp", 5: "ftp", 6: "webdav", 7: "s3"}
_SECRET_KEYS = {
    "password",
    "passwordplain",
    "proxypassword",
    "proxypasswordplain",
    "tunnelpassword",
    "tunnelpasswordplain",
    "passphrase",
    "passphraseplain",
    "tunnelpassphrase",
    "tunnelpassphraseplain",
    "s3sessiontoken",
}
_WINDOWS_PATH = re.compile(r"^[A-Za-z]:[\\/]")


@dataclass(frozen=True, slots=True)
class WinSCPImportResult:
    sessions: tuple[SessionConfig, ...]
    warnings: tuple[str, ...]
    credentials: tuple[WinSCPImportedCredential, ...] = field(default=(), repr=False)


@dataclass(frozen=True, slots=True)
class WinSCPImportedCredential:
    session_name: str
    password: str = field(repr=False)


class _WinSCPConfigParser(configparser.RawConfigParser):
    def optionxform(self, optionstr: str) -> str:
        return optionstr


def _decode_file(path: Path) -> str:
    payload = path.read_bytes()
    if payload.startswith((b"\xff\xfe", b"\xfe\xff")):
        return payload.decode("utf-16")
    try:
        return payload.decode("utf-8-sig")
    except UnicodeDecodeError:
        # Old WinSCP releases could export using the active Windows code page.
        return payload.decode("cp1252")


def _unmunge(value: str) -> str:
    """Decode WinSCP/PuTTY percent-escaped INI names and string values."""
    if "%" not in value:
        return value
    decoded = unquote_to_bytes(value)
    if decoded.startswith(b"\xef\xbb\xbf"):
        return decoded.decode("utf-8-sig")
    try:
        return decoded.decode("utf-8")
    except UnicodeDecodeError:
        return decoded.decode("cp1252")


def _integer(values: dict[str, str], key: str, default: int, name: str, warnings: list[str]) -> int:
    raw = values.get(key.casefold())
    if raw is None or not raw.strip():
        return default
    try:
        return int(raw)
    except ValueError:
        warnings.append(f"{name}: invalid {key} value {raw!r}; using {default}")
        return default


def _truthy(value: str | None) -> bool:
    return (value or "").strip().casefold() in {"1", "true", "yes", "on"}


def _decrypt_next(encoded: str, offset: int) -> tuple[int, int]:
    if offset + 2 > len(encoded):
        raise ValueError("truncated password")
    try:
        value = int(encoded[offset : offset + 2], 16)
    except ValueError as exc:
        raise ValueError("password is not hexadecimal") from exc
    return (~(value ^ 0xA3)) & 0xFF, offset + 2


def decrypt_winscp_password(encoded: str, key: str) -> str:
    """Decode WinSCP's standard reversible password format.

    Master-password-protected (external/AES) values intentionally require
    WinSCP's master password flow and are rejected here.
    """
    encoded = encoded.strip()
    offset = 0
    flag, offset = _decrypt_next(encoded, offset)
    if flag == 0xFF:
        version, offset = _decrypt_next(encoded, offset)
        if version == 1:
            raise ValueError("password is protected by a WinSCP master password")
        if version == 0:
            length, offset = _decrypt_next(encoded, offset)
        elif version == 2:
            high, offset = _decrypt_next(encoded, offset)
            low, offset = _decrypt_next(encoded, offset)
            length = (high << 8) + low
        else:
            raise ValueError(f"unsupported WinSCP password format {version}")
    else:
        length = flag
    shift, offset = _decrypt_next(encoded, offset)
    offset += shift * 2
    decrypted = bytearray()
    for _ in range(length):
        value, offset = _decrypt_next(encoded, offset)
        decrypted.append(value)
    if flag == 0xFF:
        key_bytes = key.encode("utf-8")
        if not decrypted.startswith(key_bytes):
            raise ValueError("password does not match the imported site")
        del decrypted[: len(key_bytes)]
    try:
        return decrypted.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ValueError("password is not valid UTF-8") from exc


def _endpoint(host: str, port: int, tls: bool) -> str:
    scheme = "https" if tls else "http"
    standard = 443 if tls else 80
    suffix = "" if port == standard else f":{port}"
    return f"{scheme}://{host}{suffix}"


def _s3_location(
    host: str, remote: str, port: int, tls: bool, name: str, warnings: list[str]
) -> tuple[str, str, str | None]:
    parts = [part for part in PurePosixPath(remote).parts if part not in {"", "/"}]
    if parts:
        bucket = parts[0]
        path = "/" + "/".join(parts[1:]) if len(parts) > 1 else "/"
        return bucket, path, _endpoint(host, port, tls)
    warnings.append(f"{name}: S3 backup has no bucket in RemoteDirectory; treating HostName as the bucket")
    return host, "/", None


def load_winscp_ini(path: Path) -> WinSCPImportResult:
    """Load DebSCP profiles and recover importable WinSCP credentials."""
    parser = _WinSCPConfigParser(interpolation=None, strict=False, empty_lines_in_values=False)
    try:
        parser.read_string(_decode_file(path), source=str(path))
    except (configparser.Error, UnicodeError) as exc:
        raise ValueError(f"Cannot parse WinSCP INI backup: {exc}") from exc

    def section_values(section: str) -> dict[str, str]:
        return {key.casefold(): _unmunge(value) for key, value in parser.items(section)}

    defaults: dict[str, str] = {}
    for section in parser.sections():
        if section.casefold().startswith("sessions\\"):
            encoded_name = section[len("Sessions\\") :]
            if _unmunge(encoded_name).strip().casefold() == "default settings":
                defaults = section_values(section)
                break

    sessions: list[SessionConfig] = []
    warnings: list[str] = []
    credentials: list[WinSCPImportedCredential] = []
    windows_local_directories = 0
    for section in parser.sections():
        if not section.casefold().startswith("sessions\\"):
            continue
        encoded_name = section[len("Sessions\\") :]
        name = _unmunge(encoded_name).strip()
        if not name or name.casefold() == "default settings":
            continue
        values = {**defaults, **section_values(section)}
        local_directory = values.get("localdirectory", "").strip()
        if _WINDOWS_PATH.match(local_directory) or local_directory.startswith("\\\\"):
            windows_local_directories += 1
        if _truthy(values.get("isworkspace")) or values.get("link"):
            warnings.append(f"{name}: skipped WinSCP workspace entry")
            continue
        host = values.get("hostname", "").strip()
        if not host:
            warnings.append(f"{name}: skipped because HostName is missing")
            continue
        username = values.get("username", "").strip()
        if "@" in host and not host.startswith("["):
            embedded_user, host = host.rsplit("@", 1)
            username = embedded_user or username

        protocol_id = _integer(values, "FSProtocol", 1, name, warnings)
        protocol = _PROTOCOLS.get(protocol_id)
        if protocol is None:
            warnings.append(f"{name}: skipped unsupported FSProtocol {protocol_id}")
            continue
        ftps = _integer(values, "Ftps", 0, name, warnings)
        tls = ftps != 0
        if protocol == "ftp" and tls:
            protocol = "ftps-implicit" if ftps == 1 else "ftps"
        elif protocol == "webdav" and tls:
            protocol = "webdavs"

        fallback_port = default_port(protocol)
        port = _integer(values, "PortNumber", fallback_port, name, warnings)
        if not 1 <= port <= 65535:
            warnings.append(f"{name}: invalid PortNumber {port}; using {fallback_port}")
            port = fallback_port
        remote_path = normalize_remote_path(values.get("remotedirectory", "/") or "/")
        endpoint_url: str | None = None
        region = values.get("s3defaultregion") or None
        if protocol == "s3":
            # WinSCP stores the S3 endpoint as HostName and the bucket as the
            # first RemoteDirectory component. DebSCP stores those separately.
            host, remote_path, endpoint_url = _s3_location(host, remote_path, port, tls, name, warnings)

        jump_host: str | None = None
        if _truthy(values.get("tunnel")) and values.get("tunnelhostname"):
            jump_host = values["tunnelhostname"].strip()
            tunnel_user = values.get("tunnelusername", "").strip()
            tunnel_port = _integer(values, "TunnelPortNumber", 22, name, warnings)
            destination = f"{tunnel_user}@{jump_host}" if tunnel_user else jump_host
            if tunnel_port != 22:
                jump_host = f"-p {tunnel_port} {destination}"
            else:
                jump_host = destination
            if values.get("tunnelpublickeyfile"):
                warnings.append(f"{name}: tunnel key file needs manual SSH configuration")

        proxy_command: str | None = None
        proxy_method = _integer(values, "ProxyMethod", 0, name, warnings)
        if proxy_method == 5 and values.get("proxylocalcommand"):
            proxy_command = values["proxylocalcommand"].strip()
            proxy_command = proxy_command.replace("%host", host).replace("%port", str(port))
        elif proxy_method:
            warnings.append(f"{name}: WinSCP proxy type {proxy_method} needs manual configuration")

        plain_password = values.get("passwordplain")
        encrypted_password = values.get("password")
        if plain_password is not None:
            credentials.append(WinSCPImportedCredential(name, plain_password))
        elif encrypted_password:
            try:
                password = decrypt_winscp_password(encrypted_password, username + host)
            except ValueError as exc:
                warnings.append(f"{name}: password was not imported ({exc})")
            else:
                credentials.append(WinSCPImportedCredential(name, password))

        other_secret_fields = sorted(
            key for key in values if key in _SECRET_KEYS - {"password", "passwordplain"} and values[key]
        )
        if other_secret_fields:
            warnings.append(f"{name}: additional credentials were not imported ({', '.join(other_secret_fields)})")

        sessions.append(
            SessionConfig(
                name=name,
                host=host,
                username=username,
                port=port,
                key_file=values.get("publickeyfile") or None,
                remote_path=remote_path,
                protocol=protocol,
                tls=tls,
                endpoint_url=endpoint_url,
                region=region,
                proxy_command=proxy_command,
                jump_host=jump_host,
            )
        )
    if windows_local_directories:
        warnings.append(
            f"{windows_local_directories} site(s): Windows LocalDirectory values were not imported because "
            "they are not valid Linux paths"
        )
    return WinSCPImportResult(tuple(sessions), tuple(warnings), tuple(credentials))
