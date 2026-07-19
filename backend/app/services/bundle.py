"""Court bundle: ZIP of report + annotated media + raw JSON + hash manifest."""
import json
import zipfile
from pathlib import Path

from app.services.hashing import sha256_file


def build_bundle(dst: Path, files: list[tuple[Path, str]], docs: dict[str, dict | list]) -> dict:
    """files: (absolute path, arcname). docs: arcname → JSON-serializable payload.

    Returns the manifest {arcname: sha256} (also written inside as manifest.sha256).
    """
    dst.parent.mkdir(parents=True, exist_ok=True)
    manifest: dict[str, str] = {}
    with zipfile.ZipFile(dst, "w", zipfile.ZIP_DEFLATED) as zf:
        for path, arcname in files:
            if not path.exists():
                continue
            zf.write(path, arcname)
            manifest[arcname] = sha256_file(path)
        for arcname, payload in docs.items():
            data = json.dumps(payload, ensure_ascii=False, indent=1).encode("utf-8")
            zf.writestr(arcname, data)
            import hashlib
            manifest[arcname] = hashlib.sha256(data).hexdigest()
        lines = "\n".join(f"{h}  {name}" for name, h in sorted(manifest.items()))
        zf.writestr("manifest.sha256", lines + "\n")
    return manifest
