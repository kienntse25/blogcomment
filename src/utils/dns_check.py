# src/utils/dns_check.py
import socket
import requests

def dns_check(url, timeout=5):
    """
    Kiểm tra khả năng truy cập của URL:
    - Phân giải DNS
    - Gửi HEAD request

    Trả về tuple (ok: bool, lý_do: str)
    """
    try:
        # Phân giải DNS
        host = url.split("//")[-1].split("/")[0]
        socket.gethostbyname(host)

        # Kiểm tra phản hồi HTTP
        try:
            r = requests.head(url, timeout=timeout, allow_redirects=True)
            if r.status_code >= 400:
                return False, f"URL phản hồi mã lỗi {r.status_code}"
            return True, ""
        except requests.RequestException as e:
            return False, f"URL không phản hồi: {e}"

    except socket.gaierror as e:
        return False, f"Không phân giải DNS: {e}"
    except Exception as e:
        return False, str(e)
