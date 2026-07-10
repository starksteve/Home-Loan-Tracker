from __future__ import annotations

import base64
import json
from pathlib import Path
from typing import Any

DEFAULT_DATA: dict[str, Any] = {
    "loan": {
        "principal": 1125000.0,
        "disbursement_date": "2022-05-31",
        "start_date": "2022-06-01",
        "tenure_years": 15,
        "assumed_annual_rate": 8.5,
    },
    "rate_changes": [],
    "payments": [],
}


# ---------------------------------------------------------------------------
# GitHub-backed persistence (works on Streamlit Cloud, survives redeploys)
# ---------------------------------------------------------------------------
def _get_github_config() -> dict[str, str] | None:
    """Read GitHub persistence config from Streamlit secrets.

    Expected secrets (in Streamlit Cloud -> App -> Settings -> Secrets):

        [github]
        token = "ghp_xxx"           # a fine-grained PAT with Contents: Read/Write
        repo = "starksteve/Home-Loan-Tracker"
        path = "data/loan_data.json"
        branch = "main"
    """
    try:
        import streamlit as st  # imported lazily so tests don't require it

        if "github" not in st.secrets:
            return None
        gh = st.secrets["github"]
        token = gh.get("token")
        repo = gh.get("repo")
        if not token or not repo:
            return None
        return {
            "token": token,
            "repo": repo,
            "path": gh.get("path", "data/loan_data.json"),
            "branch": gh.get("branch", "main"),
        }
    except Exception:
        return None


def _github_read(cfg: dict[str, str]) -> tuple[dict[str, Any] | None, str | None]:
    """Return (data, sha) from GitHub, or (None, None) if unavailable."""
    import requests

    url = f"https://api.github.com/repos/{cfg['repo']}/contents/{cfg['path']}"
    headers = {
        "Authorization": f"Bearer {cfg['token']}",
        "Accept": "application/vnd.github+json",
    }
    resp = requests.get(url, headers=headers, params={"ref": cfg["branch"]}, timeout=15)
    if resp.status_code == 404:
        return None, None
    resp.raise_for_status()
    payload = resp.json()
    content = base64.b64decode(payload["content"]).decode("utf-8")
    return json.loads(content), payload.get("sha")


def _github_write(cfg: dict[str, str], data: dict[str, Any]) -> None:
    import requests

    url = f"https://api.github.com/repos/{cfg['repo']}/contents/{cfg['path']}"
    headers = {
        "Authorization": f"Bearer {cfg['token']}",
        "Accept": "application/vnd.github+json",
    }
    # Need the current sha to update an existing file.
    _, sha = _github_read(cfg)
    content_b64 = base64.b64encode(
        json.dumps(data, indent=2).encode("utf-8")
    ).decode("utf-8")
    body: dict[str, Any] = {
        "message": "Update loan data via app",
        "content": content_b64,
        "branch": cfg["branch"],
    }
    if sha:
        body["sha"] = sha
    resp = requests.put(url, headers=headers, json=body, timeout=15)
    resp.raise_for_status()


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------
def load_data(path: Path) -> dict[str, Any]:
    cfg = _get_github_config()
    if cfg is not None:
        try:
            remote, _ = _github_read(cfg)
            if remote is not None:
                merged = DEFAULT_DATA.copy()
                merged.update(remote)
                return merged
        except Exception:
            # Fall back to local file on any remote failure.
            pass

    if not path.exists():
        return DEFAULT_DATA.copy()
    with path.open("r", encoding="utf-8") as file:
        data = json.load(file)

    merged = DEFAULT_DATA.copy()
    merged.update(data)
    return merged


def save_data(path: Path, data: dict[str, Any]) -> None:
    # Always keep a local copy (fallback + local runs).
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as file:
        json.dump(data, file, indent=2)

    cfg = _get_github_config()
    if cfg is not None:
        try:
            _github_write(cfg, data)
        except Exception:
            # Local copy already written; ignore remote failure silently.
            pass

