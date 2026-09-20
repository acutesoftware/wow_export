from __future__ import annotations

import json
import subprocess
from dataclasses import asdict, dataclass
from pathlib import Path
from urllib.parse import urlparse
from urllib.request import Request, urlopen


class BridgeError(RuntimeError):
    pass


@dataclass(slots=True)
class ProbeResult:
    executable: str
    exists: bool
    version: str | None = None
    automation_endpoint: str | None = None
    automation_available: bool = False
    supported_formats: tuple[str, ...] = ()
    detail: str = ""


@dataclass(frozen=True, slots=True)
class ExportResult:
    files: tuple[Path, ...]
    metadata: dict


class WowExportAdapter:
    """Version-pinned, loopback-only adapter for an RPC-capable wow.export build."""

    INTERFACE = "wow-timecapsule-bridge/v1"
    DEFAULT_BRIDGE = "http://127.0.0.1:17890"

    def __init__(self, executable: str | Path, bridge_url: str = DEFAULT_BRIDGE):
        self.executable = Path(executable)
        parsed = urlparse(bridge_url)
        if parsed.scheme != "http" or parsed.hostname != "127.0.0.1":
            raise ValueError("wow.export bridge must use http://127.0.0.1")
        self.bridge_url = bridge_url.rstrip("/")

    def probe(self) -> ProbeResult:
        result = ProbeResult(str(self.executable), self.executable.is_file())
        result.version = self.get_version() if result.exists else None
        try:
            payload = self._request("GET", "/v1/capabilities")
            if payload.get("interface") != self.INTERFACE:
                raise BridgeError("incompatible bridge interface")
            result.automation_available = True
            result.automation_endpoint = self.bridge_url
            result.supported_formats = tuple(payload.get("formats", ()))
            result.version = payload.get("wow_export_version") or result.version
            if not result.exists:
                result.detail = "Bridge available; configured executable not found"
        except Exception as exc:
            result.detail = f"No compatible localhost bridge: {type(exc).__name__}: {exc}"
        return result

    def get_version(self) -> str | None:
        for flag in ("--version", "-v"):
            try:
                completed = subprocess.run(
                    [str(self.executable), flag], capture_output=True, text=True, timeout=3,
                    creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0), check=False,
                )
                output = (completed.stdout or completed.stderr).strip()
                if output and completed.returncode == 0:
                    return output.splitlines()[0][:200]
            except (OSError, subprocess.TimeoutExpired):
                pass
        return None

    def write_diagnostic(self, path: Path) -> ProbeResult:
        result = self.probe()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(asdict(result), indent=2), encoding="utf-8")
        return result

    def open_installation(self, path: Path, product: str) -> dict:
        return self._request("POST", "/v1/installations/open", {
            "interface": self.INTERFACE, "installation": str(path.resolve()), "product": product,
        })

    def export_character(self, character_spec: dict, output_dir: Path) -> ExportResult:
        return self._export("/v1/exports/character", {"character": character_spec}, output_dir)

    def export_creature(self, display_id: int, output_dir: Path) -> ExportResult:
        return self._export("/v1/exports/creature", {"display_id": display_id}, output_dir)

    def export_map(self, map_id: int, tiles: list[dict], output_dir: Path) -> ExportResult:
        return self._export("/v1/exports/map", {"map_id": map_id, "tiles": tiles}, output_dir)

    def _export(self, endpoint: str, values: dict, output_dir: Path) -> ExportResult:
        output_dir.mkdir(parents=True, exist_ok=True)
        response = self._request("POST", endpoint, {
            "interface": self.INTERFACE, "output_dir": str(output_dir.resolve()), "format": "glb", **values,
        }, timeout=600)
        if response.get("status") != "complete":
            raise BridgeError(response.get("error") or "bridge export did not complete")
        root = output_dir.resolve()
        files: list[Path] = []
        for value in response.get("files", []):
            candidate = (root / value).resolve() if not Path(value).is_absolute() else Path(value).resolve()
            if candidate != root and root not in candidate.parents:
                raise BridgeError(f"bridge returned path outside staging directory: {value}")
            if not candidate.is_file():
                raise BridgeError(f"bridge output is missing: {value}")
            files.append(candidate)
        if not any(path.suffix.lower() == ".glb" for path in files):
            raise BridgeError("bridge did not produce a GLB")
        return ExportResult(tuple(files), response)

    def _request(self, method: str, endpoint: str, payload: dict | None = None, timeout: float = 2) -> dict:
        body = json.dumps(payload).encode() if payload is not None else None
        request = Request(self.bridge_url + endpoint, data=body, method=method, headers={"Content-Type": "application/json"})
        with urlopen(request, timeout=timeout) as response:  # noqa: S310; URL is loopback-validated
            result = json.load(response)
        if not isinstance(result, dict):
            raise BridgeError("bridge returned a non-object response")
        return result

