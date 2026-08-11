"""Validation and execution of approved, packet-scoped website file changes."""

from __future__ import annotations

from fnmatch import fnmatch
from html.parser import HTMLParser
import re
from urllib.parse import urlparse
from xml.sax.saxutils import escape as xml_escape

from app.github_service import GitHubAppAdapter, GitHubIntegrationError


class WebsiteExecutionError(ValueError):
    pass


class _GeneratedPageParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.title_count = 0
        self.h1_count = 0
        self.links = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        tag = tag.casefold()
        if tag == "title":
            self.title_count += 1
        elif tag == "h1":
            self.h1_count += 1
        elif tag == "a":
            self.links += 1


def audit_generated_website_files(files: list[dict[str, str]]) -> dict[str, object]:
    """Return deterministic page inventory and technical checks for a draft.

    This does not claim the production site is healthy. It verifies only what is
    present in the returned file set; deployment and independent verification
    remain separate boundaries.
    """
    paths = sorted(str(item.get("path", "")) for item in files)
    html_paths = [path for path in paths if path.casefold().endswith((".html", ".htm"))]
    page_checks: list[dict[str, object]] = []
    for item in files:
        path = str(item.get("path", ""))
        if path not in html_paths:
            continue
        parser = _GeneratedPageParser()
        try:
            parser.feed(str(item.get("content", ""))[:2_000_000])
            parse_status = "passed"
        except Exception:  # pragma: no cover - defensive parser boundary
            parse_status = "failed"
        page_checks.append(
            {
                "path": path,
                "parse_status": parse_status,
                "title_count": parser.title_count,
                "h1_count": parser.h1_count,
                "link_count": parser.links,
                "title_check": "passed" if parser.title_count == 1 else "failed",
                "h1_check": "passed" if parser.h1_count == 1 else "failed",
            }
        )
    sitemap_paths = [path for path in paths if path.casefold() in {"public/sitemap.xml", "sitemap.xml"}]
    robots_paths = [path for path in paths if path.casefold() in {"public/robots.txt", "robots.txt"}]
    checks = {
        "files_validated": bool(paths),
        "page_inventory_present": bool(html_paths),
        "sitemap_present": bool(sitemap_paths),
        "robots_present": bool(robots_paths),
        "html_pages_have_one_title": bool(html_paths) and all(item["title_check"] == "passed" for item in page_checks),
        "html_pages_have_one_h1": bool(html_paths) and all(item["h1_check"] == "passed" for item in page_checks),
        "html_pages_parse": bool(html_paths) and all(item["parse_status"] == "passed" for item in page_checks),
    }
    return {
        "page_inventory": html_paths,
        "page_checks": page_checks,
        "sitemap_paths": sitemap_paths,
        "robots_paths": robots_paths,
        "checks": checks,
        "passed": sum(value is True for value in checks.values()),
        "failed": sum(value is False for value in checks.values()),
    }


SECRET_PATTERNS = (
    re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----"),
    re.compile(r"(?:OPENAI|GOOGLE|SLACK|VERCEL|GITHUB)[A-Z_]*\s*=\s*[^\s]+"),
)


def ensure_site_artifacts(files: list[dict[str, str]], domain: str) -> list[dict[str, str]]:
    """Add deterministic sitemap and robots artifacts when the draft omits them."""
    output = [dict(item) for item in files]
    paths = {str(item.get("path", "")) for item in output}
    routes: set[str] = set()
    for path in paths:
        normalized = path.replace("\\", "/")
        if normalized.casefold().endswith((".html", ".htm")):
            route = normalized.removeprefix("public/").removesuffix(".html").removesuffix(".htm")
            routes.add("/" if route in {"index", "home"} else f"/{route.strip('/')}")
        match = re.search(r"(?:^|/)app/(.+?)/page\.(?:tsx?|jsx?)$", normalized)
        if match:
            route = re.sub(r"\[(?:\.\.\.)?[^]]+\]", "", match.group(1)).strip("/")
            routes.add(f"/{route}" if route else "/")
        if re.match(r"^pages/(?:index|home)\.(?:tsx?|jsx?)$", normalized):
            routes.add("/")
    if not routes and any(path.casefold().endswith(("/page.tsx", "/page.jsx", "/index.tsx", "/index.jsx")) for path in paths):
        routes.add("/")
    routes = routes or {"/"}
    parsed = urlparse(domain if "://" in domain else f"https://{domain}")
    origin = f"{parsed.scheme or 'https'}://{parsed.netloc}" if parsed.netloc else f"https://{parsed.path.strip('/')}"
    origin = xml_escape(origin, {"'": "&apos;", '"': "&quot;"})
    if "public/sitemap.xml" not in paths and "sitemap.xml" not in paths:
        urls = "\n".join(f"  <url><loc>{origin}{route}</loc></url>" for route in sorted(routes))
        output.append(
            {
                "path": "public/sitemap.xml",
                "content": f'<?xml version="1.0" encoding="UTF-8"?>\n<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n{urls}\n</urlset>\n',
            }
        )
    if "public/robots.txt" not in paths and "robots.txt" not in paths:
        output.append(
            {
                "path": "public/robots.txt",
                "content": f"User-agent: *\nAllow: /\nSitemap: {origin}/sitemap.xml\n",
            }
        )
    return output


def validate_files(files: list[dict[str, str]], allowed_paths: list[str], prohibited_paths: list[str]) -> None:
    if not files:
        raise WebsiteExecutionError("website_files_required")
    seen: set[str] = set()
    for item in files:
        path = item.get("path", "")
        content = item.get("content", "")
        if not path or path.startswith("/") or ".." in path.split("/") or path in seen:
            raise WebsiteExecutionError("website_file_path_invalid")
        if any(fnmatch(path, pattern) for pattern in prohibited_paths):
            raise WebsiteExecutionError("website_file_path_prohibited")
        if not any(fnmatch(path, pattern) for pattern in allowed_paths):
            raise WebsiteExecutionError("website_file_path_outside_packet")
        if any(pattern.search(content) for pattern in SECRET_PATTERNS):
            raise WebsiteExecutionError("website_file_secret_detected")
        seen.add(path)


def commit_website_files(*, owner: str, repository: str, branch: str, files: list[dict[str, str]], allowed_paths: list[str], prohibited_paths: list[str], commit_message: str) -> dict[str, object]:
    validate_files(files, allowed_paths, prohibited_paths)
    try:
        return GitHubAppAdapter().commit_files(owner, repository, branch, files, commit_message)
    except GitHubIntegrationError as error:
        raise WebsiteExecutionError(error.code) from error


def revert_website_commit(*, owner: str, repository: str, branch: str, commit_sha: str) -> dict[str, object]:
    try:
        return GitHubAppAdapter().revert_commit(owner, repository, commit_sha, branch)
    except GitHubIntegrationError as error:
        raise WebsiteExecutionError(error.code) from error
