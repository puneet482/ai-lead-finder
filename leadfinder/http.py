"""Polite HTTP: robots.txt, per-host rate limit, retries w/ backoff + jitter, 429 handling."""
import os, random, time
from urllib import robotparser
from urllib.parse import urlparse
import requests

# Honest, identifying UA (OSM/Nominatim require one; placeholder contacts get blocked). Set LEADFINDER_CONTACT to your email/URL.
CONTACT = os.getenv("LEADFINDER_CONTACT", "https://github.com/puneet482")
UA = f"LeadFinderMVP/0.1 ({CONTACT})"


class PoliteFetcher:
    def __init__(self, min_delay=2.0, retries=3, timeout=10):
        self.min_delay, self.retries, self.timeout = min_delay, retries, timeout
        self._last: dict[str, float] = {}
        self._robots: dict[str, robotparser.RobotFileParser | None] = {}
        self.s = requests.Session()
        self.s.headers["User-Agent"] = UA

    def _allowed(self, url: str) -> bool:
        host = urlparse(url).netloc
        if host not in self._robots:
            rp = robotparser.RobotFileParser()
            try:
                rp.set_url(f"{urlparse(url).scheme}://{host}/robots.txt"); rp.read()
            except Exception:
                rp = None  # robots unreachable -> allow, as most crawlers do
            self._robots[host] = rp
        rp = self._robots[host]
        return True if rp is None else rp.can_fetch(UA, url)

    def get(self, url: str) -> str | None:
        if not self._allowed(url):
            return None
        host = urlparse(url).netloc
        for attempt in range(self.retries):
            wait = self.min_delay - (time.time() - self._last.get(host, 0))
            if wait > 0:
                time.sleep(wait)
            self._last[host] = time.time()
            try:
                r = self.s.get(url, timeout=self.timeout)
                if r.status_code == 429:
                    time.sleep(min(int(r.headers.get("Retry-After", 5)), 30)); continue
                if r.status_code >= 500:
                    raise requests.HTTPError(r.status_code)
                return r.text if r.ok else None
            except requests.RequestException:
                time.sleep((2 ** attempt) + random.random())
        return None
