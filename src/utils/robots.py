import urllib.robotparser as rp

_cache = {}

def is_allowed(url: str, ua: str = "*") -> bool:
    from urllib.parse import urlsplit, urlunsplit
    parts = urlsplit(url)
    robots_url = urlunsplit((parts.scheme, parts.netloc, "/robots.txt", "", ""))

    if robots_url not in _cache:
        parser = rp.RobotFileParser()
        try:
            parser.set_url(robots_url)
            parser.read()
        except Exception:
            _cache[robots_url] = None
        else:
            _cache[robots_url] = parser

    parser = _cache.get(robots_url)
    if parser is None:
        # Không đọc được robots.txt -> cho qua (tuỳ bạn thay đổi thành False nếu muốn chặt chẽ)
        return True
    return parser.can_fetch(ua, url)
