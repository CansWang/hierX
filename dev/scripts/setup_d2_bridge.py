"""Explicit SDK/bootstrap/build installer; never invoked by Hx runtime commands."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import platform
import re
import shlex
import shutil
import subprocess
import sys
import tarfile
import tempfile
import urllib.request

GO_VERSION = "1.27.3"
MIN_GO = (1, 27, 0)
# Official https://go.dev/dl/ release digests; update alongside the pinned version.
GO_SHA256 = {
    ("linux", "amd64"): "65efbc80fdc1fa2cd2631cad5b481777a68e8725f34e89f50fc6ac714e379b40",
    ("linux", "arm64"): "a06e99309dbcbdca1a8ccd2282c3ee146e55930886e26b4f1193269587165f49",
    ("darwin", "amd64"): "b6f8e931e4ab497fcde6da8ae4499a58f9d258e55c8a80824a516eae5950a750",
    ("darwin", "arm64"): "dd3908cf20959d798c1e06ebe5b72213f0505ce01373b40ce3110975a6cd99c2",
}
REPO = Path(__file__).resolve().parents[2]


class SetupError(ValueError):
    """An explicit installer operation failed; existing installations are retained."""


def version(executable: str | Path) -> tuple[int, int, int] | None:
    """Inspect the installed compiler without Go's implicit toolchain downloader."""
    try:
        result = subprocess.run([str(executable), "version"], text=True, capture_output=True,
                                timeout=10, cwd=REPO, env={**os.environ, "GOTOOLCHAIN": "local"})
    except (OSError, subprocess.SubprocessError):
        return None
    match = re.search(r"\bgo(\d+)\.(\d+)(?:\.(\d+))?(?:\s|$)", result.stdout)
    return tuple(int(p or 0) for p in match.groups()) if result.returncode == 0 and match else None


def asset() -> tuple[str, str]:
    system = platform.system().lower()
    machine = platform.machine().lower()
    arch = {"x86_64": "amd64", "amd64": "amd64", "aarch64": "arm64", "arm64": "arm64"}.get(machine)
    digest = GO_SHA256.get((system, arch))
    if not digest:
        raise SetupError(f"Automatic Go setup does not support {system}/{machine}; install Go 1.27+ from https://go.dev/dl/ and put it on PATH")
    return f"go{GO_VERSION}.{system}-{arch}.tar.gz", digest


def download(url: str, target: Path) -> str:
    digest = hashlib.sha256()
    with urllib.request.urlopen(url, timeout=60) as response, target.open("wb") as output:
        while chunk := response.read(1024 * 1024):
            digest.update(chunk)
            output.write(chunk)
    return digest.hexdigest()


def extract_sdk(archive: Path, target: Path) -> None:
    """Extract regular SDK files/directories only, including on Python 3.10."""
    with tarfile.open(archive, "r:gz") as tar:
        for member in tar.getmembers():
            path = PurePosixPath(member.name)
            if (not path.parts or path.parts[0] != "go" or path.is_absolute()
                    or ".." in path.parts or not (member.isfile() or member.isdir())):
                raise SetupError(f"Unsafe Go SDK archive entry: {member.name}")
        for member in tar.getmembers():
            path = target / member.name
            if member.isdir():
                path.mkdir(parents=True, exist_ok=True)
            else:
                path.parent.mkdir(parents=True, exist_ok=True)
                with tar.extractfile(member) as source, path.open("wb") as output:
                    shutil.copyfileobj(source, output)
                path.chmod(member.mode & 0o777)


def resolve_go(sdk_dir: Path, bootstrap: bool = True) -> Path:
    existing = shutil.which("go")
    if existing and (version(existing) or (0, 0, 0)) >= MIN_GO:
        return Path(existing).absolute()
    cached = sdk_dir / "bin/go"
    if (version(cached) or (0, 0, 0)) >= MIN_GO:
        return cached
    if not bootstrap:
        raise SetupError("Go 1.27+ is required; --no-bootstrap disables SDK installation. Put a compatible Go on PATH or rerun without --no-bootstrap")
    if sdk_dir.exists():
        raise SetupError(f"Go SDK location {sdk_dir} exists but has no working Go 1.27+; choose another --go-dir or repair that installation")
    name, expected = asset()
    sdk_dir.parent.mkdir(parents=True, exist_ok=True)
    print(f"Installing Go {GO_VERSION} in {sdk_dir}", file=sys.stderr)
    with tempfile.TemporaryDirectory(prefix=".hx-go-", dir=sdk_dir.parent) as temporary:
        staging = Path(temporary)
        archive = staging / name
        print(f"Downloading https://go.dev/dl/{name}", file=sys.stderr)
        actual = download("https://go.dev/dl/" + name, archive)
        if actual != expected:
            raise SetupError(f"Go SDK SHA-256 mismatch: expected {expected}, got {actual}")
        print("Go SDK SHA-256 verified", file=sys.stderr)
        extract_sdk(archive, staging)
        if version(staging / "go/bin/go") != (1, 27, 3):
            raise SetupError("Downloaded SDK did not report Go 1.27.3")
        try:
            (staging / "go").rename(sdk_dir)
        except FileExistsError:
            # Another explicit setup can finish while this one is downloading.
            if (version(cached) or (0, 0, 0)) < MIN_GO:
                raise SetupError(f"Another installation appeared at {sdk_dir}; it is not a compatible Go SDK")
    return cached


def build(go: Path, destination: Path) -> str:
    destination.parent.mkdir(parents=True, exist_ok=True)
    environment = {**os.environ, "GOTOOLCHAIN": "local",
                   "PATH": str(go.parent) + os.pathsep + os.environ.get("PATH", "")}
    with tempfile.TemporaryDirectory(prefix=".hx-d2-build-", dir=destination.parent) as temporary:
        binary = Path(temporary) / "hx-d2-bridge"
        subprocess.run([str(go), "build", "-mod=readonly", "-trimpath", "-o", str(binary), "."],
                       cwd=REPO / "dev/d2_bridge", env=environment, check=True)
        result = subprocess.run([str(binary), "--version"], text=True, capture_output=True,
                                check=True, timeout=10)
        data = json.loads(result.stdout)
        if not isinstance(data, dict) or (data.get("protocol"), data.get("d2_version"), data.get("d2_commit")) != (
                "hx-d2-bridge/1", "v0.9.0", "d5a51743b6d5c00f1ec6f8340003f5d5a6ba4eda"):
            raise SetupError("Built bridge reported an unexpected protocol/upstream version")
        os.replace(binary, destination)
    return result.stdout.strip()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Install the optional D2 bridge; bootstrap pinned user-local Go when needed.")
    parser.add_argument("destination", nargs="?", type=Path,
                        default=Path.home() / ".cache/hx/tools/bin/hx-d2-bridge", help="bridge executable destination")
    parser.add_argument("--go-dir", type=Path, default=Path.home() / f".local/lib/go{GO_VERSION}",
                        help="fallback Go SDK directory (default: ~/.local/lib/go1.27.3)")
    parser.add_argument("--no-bootstrap", action="store_true", help="require an existing compatible compiler; do not download a Go SDK")
    args = parser.parse_args(argv)
    try:
        go = resolve_go(args.go_dir.expanduser().absolute(), not args.no_bootstrap)
        selected = version(go)
        if selected is None:
            raise SetupError(f"Selected Go compiler is no longer executable: {go}")
        print(f"Using Go {'.'.join(map(str, selected))}: {go}", file=sys.stderr)
        print(f'For Go in this terminal: export PATH={shlex.quote(str(go.parent))}:"$PATH"', file=sys.stderr)
        destination = args.destination.expanduser().absolute()
        result = build(go, destination)
        print(f"Installed bridge: {destination}", file=sys.stderr)
        print(result)
        return 0
    except (OSError, ValueError, subprocess.SubprocessError, tarfile.TarError) as exc:
        print(f"D2 bridge setup failed: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
