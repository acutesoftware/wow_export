from __future__ import annotations

import json
import subprocess
from dataclasses import asdict, dataclass
from pathlib import Path
from urllib.request import urlopen


@dataclass(slots=True)
class ProbeResult:
    executable: str
    exists: bool
    version: str | None = None
    automation_endpoint: str | None = None
    automation_available: bool = False
    supported_formats: tuple[str, ...] = ()
    detail: str = ""


class WowExportAdapter:
    """Stable boundary around wow.export; Phase 1 intentionally only probes capabilities."""

    BRIDGE_URL = "http://127.0.0.1:17890/v1/capabilities"

    def __init__(self, executable: str | Path):
        self.executable = Path(executable)

    def probe(self) -> ProbeResult:
        result = ProbeResult(str(self.executable), self.executable.is_file())
        if not result.exists:
            result.detail = "Executable not found"
            return result
        result.version = self.get_version()
        try:
            with urlopen(self.BRIDGE_URL, timeout=0.35) as response:  # noqa: S310; loopback only
                payload = json.load(response)
            if payload.get("interface") == "wow-timecapsule-bridge/v1":
                result.automation_available = True
                result.automation_endpoint = self.BRIDGE_URL
                result.supported_formats = tuple(payload.get("formats", ()))
        except Exception as exc:  # capability absence is expected
            result.detail = f"No compatible localhost bridge: {type(exc).__name__}"
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
        try:
            return self.executable.stat().st_mtime_ns.__str__()
        except OSError:
            return None

    def write_diagnostic(self, path: Path) -> ProbeResult:
        result = self.probe()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(asdict(result), indent=2), encoding="utf-8")
        return result

    def open_installation(self, path: Path) -> None:
        raise NotImplementedError("wow.export automation requires a compatible v1 bridge")

    export_character = open_installation
    export_creature = open_installation
    export_map = open_installation

