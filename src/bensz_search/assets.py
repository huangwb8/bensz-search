"""Immutable public module graph, served from a process-owned content snapshot."""

import hashlib
import mimetypes
import re
import tempfile
from pathlib import Path

from fastapi.responses import Response


class Assets:
    def __init__(self, directory):
        root = Path(directory)
        self.files = {p.name: p.read_bytes() for p in sorted(root.iterdir()) if p.suffix in {".js", ".css"}}
        graph = b"".join(name.encode() + b"\0" + value for name, value in self.files.items())
        self.archive = None
        self.fingerprint = hashlib.sha256(graph).hexdigest()[:20]
        html = (root / "index.html").read_text()
        self.html = html.replace("/admin/static/", f"/admin/assets/{self.fingerprint}/").encode()

    def publish(self, directory):
        # Retain prior public bundles on the data volume across image changes.
        # Publish a complete directory with a single rename, never a mixed graph.
        archive = Path(directory) / "assets"
        archive.mkdir(parents=True, exist_ok=True)
        destination = archive / self.fingerprint
        if not destination.exists():
            temporary = Path(tempfile.mkdtemp(prefix=".bundle-", dir=archive))
            try:
                for name, content in self.files.items():
                    (temporary / name).write_bytes(content)
                try:
                    temporary.rename(destination)
                except OSError:
                    if not destination.is_dir():
                        raise
            finally:
                if temporary.exists():
                    for path in temporary.iterdir():
                        path.unlink()
                    temporary.rmdir()
        self.archive = archive

    async def __call__(self, scope, receive, send):
        parts = scope["path"].split("/")
        name = parts[-1]
        if (
            len(parts) < 2
            or not re.fullmatch(r"[a-f0-9]{20}", parts[-2])
            or not re.fullmatch(r"[a-zA-Z0-9_.-]+\.(?:js|css)", name)
        ):
            return await Response(status_code=404)(scope, receive, send)
        if parts[-2] == self.fingerprint:
            if name not in self.files:
                return await Response(status_code=404)(scope, receive, send)
            body = self.files[name]
        elif self.archive is not None:
            path = self.archive / parts[-2] / name
            if not path.is_file() or path.is_symlink():
                return await Response(status_code=404)(scope, receive, send)
            # File reads use the existing bounded Starlette thread limiter.
            import anyio

            body = await anyio.to_thread.run_sync(path.read_bytes)
        else:
            return await Response(status_code=404)(scope, receive, send)
        etag = '"' + hashlib.sha256(body).hexdigest() + '"'
        headers = {
            "Cache-Control": "public, max-age=31536000, immutable",
            "ETag": etag,
            "X-Content-Type-Options": "nosniff",
        }
        request_headers = dict(scope.get("headers", []))
        if request_headers.get(b"if-none-match", b"").decode() == etag:
            response = Response(status_code=304, headers=headers)
        else:
            response = Response(body, media_type=mimetypes.guess_type(name)[0], headers=headers)
        await response(scope, receive, send)
