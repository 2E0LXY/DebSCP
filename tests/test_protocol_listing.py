from datetime import UTC

from debscp.backends.ftp import FTPBackend
from debscp.backends.s3 import S3Backend
from debscp.backends.webdav import WebDAVBackend
from debscp.models import SessionConfig


class FakeFTP:
    def mlsd(self, path, facts):
        assert path == "/pub"
        return iter([
            ("folder", {"type": "dir", "modify": "20260817120000"}),
            ("readme.txt", {"type": "file", "size": "12", "modify": "20260817120100"}),
        ])


def test_ftp_mlsd_listing() -> None:
    backend = FTPBackend(SessionConfig("ftp", "host", "user", protocol="ftp"))
    backend.ftp = FakeFTP()
    entries = backend.listdir("/pub")
    assert [(item.name, item.is_dir, item.size) for item in entries] == [
        ("folder", True, 0), ("readme.txt", False, 12),
    ]


class FakeResponse:
    def __init__(self, content):
        self.content = content
        self.status_code = 207

    def raise_for_status(self): pass


class FakeDAVSession:
    def request(self, method, url, headers, timeout):
        assert method == "PROPFIND"
        return FakeResponse(b"""<?xml version='1.0'?><d:multistatus xmlns:d='DAV:'>
          <d:response><d:href>/files/</d:href><d:propstat><d:prop><d:resourcetype><d:collection/></d:resourcetype></d:prop></d:propstat></d:response>
          <d:response><d:href>/files/report.txt</d:href><d:propstat><d:prop><d:resourcetype/><d:getcontentlength>42</d:getcontentlength></d:prop></d:propstat></d:response>
        </d:multistatus>""")


def test_webdav_propfind_listing() -> None:
    config = SessionConfig("dav", "host", "user", port=443, remote_path="/files", protocol="webdavs", tls=True)
    backend = WebDAVBackend(config)
    backend.base_url = "https://host/"
    backend.session = FakeDAVSession()
    entries = backend.listdir("/files")
    assert len(entries) == 1
    assert entries[0].name == "report.txt"
    assert entries[0].size == 42


class FakePaginator:
    def paginate(self, **kwargs):
        return [{
            "CommonPrefixes": [{"Prefix": "build/assets/"}],
            "Contents": [{"Key": "build/app.tar", "Size": 99, "LastModified": __import__("datetime").datetime.now(UTC)}],
        }]


class FakeS3:
    def get_paginator(self, name):
        assert name == "list_objects_v2"
        return FakePaginator()


def test_s3_prefix_listing() -> None:
    backend = S3Backend(SessionConfig("s3", "bucket", "", protocol="s3"))
    backend.client = FakeS3()
    entries = backend.listdir("/build")
    assert [(item.name, item.is_dir) for item in entries] == [("assets", True), ("app.tar", False)]

