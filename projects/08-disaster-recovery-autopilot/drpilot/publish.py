"""Publish a postmortem draft as a GitHub issue, so review happens where the team already works."""

from __future__ import annotations

import json
import urllib.request

from .model import Incident


class GitHubIssuePublisher:
    def __init__(self, repo: str, token: str, api_url: str = "https://api.github.com", labels: tuple[str, ...] = ("postmortem", "draft")):
        if repo.count("/") != 1:
            raise ValueError("repo must be owner/name")
        if not api_url.startswith(("https://", "http://127.0.0.1", "http://localhost")):
            raise ValueError("api_url must be https (plain http only for a local test server)")
        self.repo, self.token, self.api_url, self.labels = repo, token, api_url.rstrip("/"), list(labels)

    def publish(self, incident: Incident, body: str) -> str:
        payload = {"title": f"Postmortem draft: {incident.title} ({incident.id})", "body": body, "labels": self.labels}
        req = urllib.request.Request(  # noqa: S310  (scheme checked in __init__)
            f"{self.api_url}/repos/{self.repo}/issues",
            data=json.dumps(payload).encode(),
            method="POST",
            headers={
                "Authorization": f"Bearer {self.token}",
                "Accept": "application/vnd.github+json",
                "X-GitHub-Api-Version": "2022-11-28",
                "Content-Type": "application/json",
            },
        )
        with urllib.request.urlopen(req, timeout=10) as resp:  # noqa: S310
            return json.loads(resp.read())["html_url"]
