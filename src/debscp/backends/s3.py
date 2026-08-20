from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path, PurePosixPath

import boto3
from boto3.s3.transfer import TransferConfig

from ..models import RemoteEntry, SessionConfig, normalize_remote_path
from ..resume import finish_partial, prepare_partial
from .base import BackendCapabilities, ProgressCallback, RemoteBackend


class S3Backend(RemoteBackend):
    capabilities = BackendCapabilities(download_resume=True, atomic_upload=True, recursive=True)

    def __init__(self, config: SessionConfig, password: str | None = None) -> None:
        self.config = config
        self.bucket = config.host
        self.password = password
        self.client = None
        self.transfer_config = TransferConfig(multipart_threshold=8 * 1024 * 1024, multipart_chunksize=8 * 1024 * 1024)

    @staticmethod
    def _key(path: str) -> str:
        return normalize_remote_path(path).lstrip("/")

    def connect(self) -> None:
        kwargs: dict[str, object] = {}
        if self.config.username:
            kwargs["aws_access_key_id"] = self.config.username
        if self.password:
            kwargs["aws_secret_access_key"] = self.password
        if self.config.endpoint_url:
            kwargs["endpoint_url"] = self.config.endpoint_url
        if self.config.region:
            kwargs["region_name"] = self.config.region
        client = boto3.client("s3", **kwargs)
        client.head_bucket(Bucket=self.bucket)
        self.client = client

    def _connection(self):
        if self.client is None:
            raise RuntimeError("Not connected")
        return self.client

    def close(self) -> None:
        if self.client is not None:
            self.client.close()
        self.client = None

    def listdir(self, path: str) -> list[RemoteEntry]:
        base = normalize_remote_path(path)
        prefix = self._key(base)
        if prefix and not prefix.endswith("/"):
            prefix += "/"
        paginator = self._connection().get_paginator("list_objects_v2")
        entries: dict[str, RemoteEntry] = {}
        for page in paginator.paginate(Bucket=self.bucket, Prefix=prefix, Delimiter="/"):
            for common in page.get("CommonPrefixes", []):
                key = common["Prefix"].rstrip("/")
                name = PurePosixPath(key).name
                entries[name] = RemoteEntry(name, "/" + key, 0, datetime.fromtimestamp(0, UTC), 0, True)
            for item in page.get("Contents", []):
                key = item["Key"]
                if key == prefix or key.endswith("/"):
                    continue
                name = PurePosixPath(key).name
                entries[name] = RemoteEntry(
                    name,
                    "/" + key,
                    int(item["Size"]),
                    item["LastModified"].astimezone(),
                    0,
                    False,
                )
        return sorted(entries.values(), key=lambda entry: (not entry.is_dir, entry.name.casefold()))

    def download(self, remote: str, local: Path, progress: ProgressCallback | None = None) -> None:
        key = self._key(remote)
        local.parent.mkdir(parents=True, exist_ok=True)
        temporary = local.with_name(local.name + ".debscp-part")
        details = self._connection().head_object(Bucket=self.bucket, Key=key)
        total = int(details["ContentLength"])
        identity = {
            "protocol": "s3",
            "bucket": self.bucket,
            "key": key,
            "size": total,
            "etag": str(details.get("ETag", "")),
            "version": str(details.get("VersionId", "")),
        }
        offset = prepare_partial(temporary, identity, total)
        if offset == total:
            finish_partial(temporary, local)
            return
        request = {"Bucket": self.bucket, "Key": key}
        if offset:
            request["Range"] = f"bytes={offset}-"
        response = self._connection().get_object(**request)
        transferred = offset
        with temporary.open("ab") as destination:
            for chunk in response["Body"].iter_chunks(chunk_size=262144):
                destination.write(chunk)
                transferred += len(chunk)
                if progress:
                    progress(transferred, total)
        finish_partial(temporary, local)

    def upload(self, local: Path, remote: str, progress: ProgressCallback | None = None) -> None:
        key = self._key(remote)
        temporary = key + ".debscp-part"
        total, transferred = local.stat().st_size, 0

        def report(amount: int) -> None:
            nonlocal transferred
            transferred += amount
            if progress:
                progress(transferred, total)

        self._connection().upload_file(
            str(local),
            self.bucket,
            temporary,
            Callback=report,
            Config=self.transfer_config,
        )
        self._connection().copy_object(
            Bucket=self.bucket, Key=key, CopySource={"Bucket": self.bucket, "Key": temporary}
        )
        self._connection().delete_object(Bucket=self.bucket, Key=temporary)

    def mkdir(self, path: str) -> None:
        key = self._key(path).rstrip("/") + "/"
        self._connection().put_object(Bucket=self.bucket, Key=key, Body=b"")

    def remove(self, path: str, *, directory: bool = False) -> None:
        key = self._key(path)
        if not key:
            raise ValueError("Refusing to remove the bucket root")
        if directory:
            prefix = key.rstrip("/") + "/"
            paginator = self._connection().get_paginator("list_objects_v2")
            for page in paginator.paginate(Bucket=self.bucket, Prefix=prefix):
                objects = [{"Key": item["Key"]} for item in page.get("Contents", [])]
                if objects:
                    self._connection().delete_objects(Bucket=self.bucket, Delete={"Objects": objects})
        else:
            self._connection().delete_object(Bucket=self.bucket, Key=key)

    def rename(self, source: str, destination: str) -> None:
        old_key, new_key = self._key(source), self._key(destination)
        old_prefix, new_prefix = old_key.rstrip("/") + "/", new_key.rstrip("/") + "/"
        paginator = self._connection().get_paginator("list_objects_v2")
        objects = [
            item["Key"]
            for page in paginator.paginate(Bucket=self.bucket, Prefix=old_prefix)
            for item in page.get("Contents", [])
        ]
        if objects:
            for key in objects:
                destination_key = new_prefix + key[len(old_prefix) :]
                self._connection().copy_object(
                    Bucket=self.bucket,
                    Key=destination_key,
                    CopySource={"Bucket": self.bucket, "Key": key},
                )
            self._connection().delete_objects(
                Bucket=self.bucket,
                Delete={"Objects": [{"Key": key} for key in objects]},
            )
        else:
            self._connection().copy_object(
                Bucket=self.bucket,
                Key=new_key,
                CopySource={"Bucket": self.bucket, "Key": old_key},
            )
            self._connection().delete_object(Bucket=self.bucket, Key=old_key)
