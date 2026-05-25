#!/usr/bin/env python3
"""
DDNS Updater für ipv64.net
==========================
Wird vom Cron-Daemon aufgerufen. Erkennt die aktuelle IP (IPv4 + IPv6),
vergleicht mit dem gespeicherten Zustand, prüft den Rate-Limiter und
sendet bei Bedarf ein Update an ipv64.net.

Aufruf-Modi:
  python ddns_updater.py               # Normaler Cron-Lauf (Update + Log-Rotation)
  python ddns_updater.py --first-run   # Erster Start (Credentials validieren)
  python ddns_updater.py --dns-check   # Nur DNS-Einträge prüfen und loggen
"""

import os
import re
import sys
import json
import socket
import argparse
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Optional

import requests
import dns.resolver
import dns.exception

try:
    import apprise
    APPRISE_AVAILABLE = True
except ImportError:
    APPRISE_AVAILABLE = False


# ── Zeitstempel-Hilfsfunktion ────────────────────────────────────────────────

def _ts() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")

def log_info(msg: str):  print(f"{_ts()}  INFO    !!!  - {msg}", flush=True)
def log_warn(msg: str):  print(f"{_ts()}  WARNUNG !!!  - {msg}", flush=True)
def log_error(msg: str): print(f"{_ts()}  FEHLER  !!!  - {msg}", flush=True)
def log_ok(msg: str):    print(f"{_ts()}  OK      !!!  - {msg}", flush=True)
def log_upd(msg: str):   print(f"{_ts()}  UPDATE  !!!  - {msg}", flush=True)
def log_rate(msg: str):  print(f"{_ts()}  RATE    !!!  - {msg}", flush=True)
def log_check(msg: str): print(f"{_ts()}  IP CHECK    - {msg}", flush=True)
def log_sep():           print("=" * 94, flush=True)


# ── Konfiguration aus Umgebungsvariablen ─────────────────────────────────────

DATA_DIR    = Path(os.environ.get("DATA_DIR", "/data"))
LOG_DIR     = DATA_DIR / "log"
STATE_IPV4  = DATA_DIR / "updip.txt"
STATE_IPV6  = DATA_DIR / "updip6.txt"
RATE_STATE  = DATA_DIR / "rate_limit_state.json"

DOMAIN_KEY        = os.environ.get("DOMAIN_KEY", "")
DOMAIN_IPV64      = os.environ.get("DOMAIN_IPV64", "")
DOMAIN_PRAEFIX_YES = os.environ.get("DOMAIN_PRAEFIX_YES", "no").lower() in ("yes", "y", "1", "true")
DOMAIN_PRAEFIX    = os.environ.get("DOMAIN_PRAEFIX", "")

IPV4_ENABLED  = os.environ.get("IPV4_ENABLED",  "yes").lower() in ("yes", "y", "1", "true")
IPV6_ENABLED  = os.environ.get("IPV6_ENABLED",  "yes").lower() in ("yes", "y", "1", "true")
IP_CHECK      = os.environ.get("IP_CHECK",      "yes").lower() in ("yes", "y", "1", "true")
NETWORK_CHECK = os.environ.get("NETWORK_CHECK", "yes").lower() in ("yes", "y", "1", "true")

NAME_SERVER  = os.environ.get("NAME_SERVER", "ns1.ipv64.net")
USER_AGENT   = os.environ.get(
    "CURL_USER_AGENT",
    "docker-ddns-ipv64-python/2.0.0 github.com/Strice91/ddns-ipv64"
)
NOTIFY_URL        = os.environ.get("NOTIFY_URL", "")
NOTIFY_SKIP_TEST  = os.environ.get("NOTIFY_SKIP_TEST", "no").lower() in ("yes", "y", "1", "true")

RATE_LIMIT_MAX_UPDATES    = int(os.environ.get("RATE_LIMIT_MAX_UPDATES",    "5"))
RATE_LIMIT_WINDOW_MINUTES = int(os.environ.get("RATE_LIMIT_WINDOW_MINUTES", "60"))

MAX_FILES = int(os.environ.get("MAX_FILES", "10"))
MAX_LINES = int(os.environ.get("MAX_LINES", "1000"))

# Regex-Muster für IP-Validierung
IPV4_RE = re.compile(r"^\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}$")
IPV6_RE = re.compile(r"^[0-9a-fA-F:]{2,45}$")

# Fallback-Quellen für IPv4-Erkennung
IPV4_SOURCES = [
    "https://ipinfo.io/ip",
    "https://ifconfig.me",
    "https://ifconfig.co/ip",
    "https://icanhazip.com",
    "https://api.ipify.org",
    "https://ipecho.net/plain",
    "https://ident.me",
    "https://checkip.amazonaws.com",
    "https://myexternalip.com/raw",
    "https://wtfismyip.com/text",
    "https://ip.tyk.nu",
    "https://ipv4.icanhazip.com",
    "https://ipv64.net/ipcheck.php?ipv4",
]

# Fallback-Quellen für IPv6-Erkennung
IPV6_SOURCES = [
    "https://ipv6.icanhazip.com",
    "https://api64.ipify.org",
    "https://ipv6.ident.me",
    "https://v6.ident.me",
    "https://ipv64.net/ipcheck.php?ipv6",
    "https://ifconfig.co/ipv6",
]

SUCCESS_RESPONSES = {"nochg", "good", "ok"}


# ── HTTP-Session ─────────────────────────────────────────────────────────────

def _session() -> requests.Session:
    sess = requests.Session()
    sess.headers.update({"User-Agent": USER_AGENT})
    return sess


# ── IPv6-System-Check ─────────────────────────────────────────────────────────

def check_ipv6_system() -> bool:
    """Prüft ob das System eine globale IPv6-Verbindung aufbauen kann."""
    try:
        s = socket.socket(socket.AF_INET6, socket.SOCK_STREAM)
        s.settimeout(3)
        s.connect(("2606:4700:4700::1111", 80))  # Cloudflare IPv6 DNS
        s.close()
        return True
    except Exception:
        return False


# ── Rate Limiter ──────────────────────────────────────────────────────────────

class RateLimiter:
    """
    Verfolgt Update-Zeitstempel in einer JSON-Datei und blockiert Updates,
    wenn das konfigurierte Limit im Zeitfenster erreicht ist.
    """

    def __init__(self):
        self.state_file = RATE_STATE
        self.max_updates = RATE_LIMIT_MAX_UPDATES
        self.window = timedelta(minutes=RATE_LIMIT_WINDOW_MINUTES)

    def _load(self) -> list[datetime]:
        if not self.state_file.exists():
            return []
        try:
            data = json.loads(self.state_file.read_text())
            result = []
            for ts_str in data.get("updates", []):
                dt = datetime.fromisoformat(ts_str)
                if dt.tzinfo is None:
                    dt = dt.replace(tzinfo=timezone.utc)
                result.append(dt)
            return result
        except Exception:
            return []

    def _save(self, timestamps: list[datetime]):
        self.state_file.parent.mkdir(parents=True, exist_ok=True)
        self.state_file.write_text(
            json.dumps(
                {"updates": [ts.isoformat() for ts in timestamps]},
                indent=2,
            )
        )

    def _active_timestamps(self) -> list[datetime]:
        """Gibt nur Timestamps zurück, die noch im Zeitfenster liegen."""
        now = datetime.now(timezone.utc)
        cutoff = now - self.window
        return [ts for ts in self._load() if ts > cutoff]

    def is_allowed(self) -> tuple[bool, int]:
        """Gibt (erlaubt, aktueller_count) zurück. Schreibt noch NICHT."""
        timestamps = self._active_timestamps()
        return len(timestamps) < self.max_updates, len(timestamps)

    def record_update(self):
        """Schreibt den aktuellen Zeitstempel in die State-Datei."""
        timestamps = self._active_timestamps()
        timestamps.append(datetime.now(timezone.utc))
        self._save(timestamps)


# ── State (gespeicherte IPs) ──────────────────────────────────────────────────

def read_state() -> tuple[str, str]:
    ipv4 = STATE_IPV4.read_text().strip() if STATE_IPV4.exists() else ""
    ipv6 = STATE_IPV6.read_text().strip() if STATE_IPV6.exists() else ""
    return ipv4, ipv6


def write_state(ip4: Optional[str], ip6: Optional[str]):
    if ip4:
        STATE_IPV4.write_text(ip4 + "\n")
    if ip6:
        STATE_IPV6.write_text(ip6 + "\n")


# ── IP-Erkennung ──────────────────────────────────────────────────────────────

def detect_ipv4() -> Optional[str]:
    log_info("IPv4 Detection gestartet...")
    sess = _session()
    for url in IPV4_SOURCES:
        try:
            resp = sess.get(url, timeout=(2, 3))
            ip = resp.text.strip()
            if IPV4_RE.match(ip):
                log_info(f"IPv4 gefunden: {ip} (Quelle: {url})")
                return ip
        except Exception:
            continue
    log_warn("Keine gültige IPv4-Adresse gefunden")
    return None


def detect_ipv6() -> Optional[str]:
    log_info("IPv6 Detection gestartet...")
    sess = _session()
    for url in IPV6_SOURCES:
        try:
            resp = sess.get(url, timeout=(2, 3))
            ip = resp.text.strip()
            if IPV6_RE.match(ip) and ":" in ip:
                log_info(f"IPv6 gefunden: {ip} (Quelle: {url})")
                return ip
        except Exception:
            continue
    log_warn("Keine gültige IPv6-Adresse gefunden")
    return None


# ── Netzwerk-Check ────────────────────────────────────────────────────────────

def network_check() -> bool:
    """Gibt True zurück, wenn ipv64.net erreichbar ist."""
    try:
        _session().get("https://ipv64.net/ipcheck.php", timeout=10)
        return True
    except Exception:
        log_error("ipv64.net ist nicht erreichbar")
        return False


# ── DNS-Lookup (ersetzt dig) ──────────────────────────────────────────────────

def _resolve_nameserver(name: str) -> list[str]:
    """Löst den Nameserver-Hostnamen in IP-Adressen auf."""
    try:
        socket.inet_aton(name)
        return [name]  # Bereits eine IP
    except socket.error:
        pass
    try:
        return [str(r) for r in dns.resolver.resolve(name, "A")]
    except Exception:
        return [name]


def dns_lookup(domain: str, record_type: str) -> list[str]:
    """Führt einen DNS-Lookup gegen den konfigurierten Nameserver durch."""
    resolver = dns.resolver.Resolver()
    resolver.nameservers = _resolve_nameserver(NAME_SERVER)
    resolver.lifetime = 5.0
    try:
        answers = resolver.resolve(domain, record_type)
        return [str(r) for r in answers]
    except Exception:
        return []


def run_dns_check():
    """Loggt die aktuellen DNS-Einträge aller konfigurierten Domains."""
    domains = [d.strip() for d in DOMAIN_IPV64.split(",") if d.strip()]
    ipv6_active = IPV6_ENABLED and check_ipv6_system()

    for domain in domains:
        full = (
            f"{DOMAIN_PRAEFIX}.{domain}"
            if DOMAIN_PRAEFIX_YES and DOMAIN_PRAEFIX
            else domain
        )
        if IPV4_ENABLED:
            result = dns_lookup(full, "A")
            log_check(f"Domain {full} hat IPv4: {', '.join(result) or 'KEINE'}")
        if ipv6_active:
            result = dns_lookup(full, "AAAA")
            log_check(f"Domain {full} hat IPv6: {', '.join(result) or 'KEINE'}")
    log_sep()


# ── Benachrichtigung (ersetzt shoutrrr-Binary) ────────────────────────────────

def send_notification(title: str, message: str):
    """Sendet eine Benachrichtigung über apprise (NOTIFY_URL)."""
    if not NOTIFY_URL:
        return
    if not APPRISE_AVAILABLE:
        log_warn("apprise nicht verfügbar – Benachrichtigung übersprungen")
        return
    try:
        ap = apprise.Apprise()
        ap.add(NOTIFY_URL)
        ap.notify(title=title, body=message)
        log_info("Benachrichtigung gesendet")
    except Exception as e:
        log_error(f"Benachrichtigung fehlgeschlagen: {e}")


# ── Log-Rotation ──────────────────────────────────────────────────────────────

def rotate_log():
    """Rotiert /data/log/cron.log wenn MAX_LINES überschritten."""
    log_file = LOG_DIR / "cron.log"
    if not log_file.exists():
        return
    try:
        line_count = sum(1 for _ in log_file.open(errors="replace"))
    except Exception:
        return
    if line_count <= MAX_LINES:
        return

    log_info(f"LOG ROTATE: {line_count} Zeilen > {MAX_LINES}, rotiere Log")
    # Ältere Backups verschieben
    for i in range(MAX_FILES, 0, -1):
        old = LOG_DIR / f"cron.log.{i}"
        newer = LOG_DIR / f"cron.log.{i + 1}"
        if old.exists():
            old.rename(newer)
    # Aktuellen Log sichern und leeren
    backup = LOG_DIR / "cron.log.1"
    content = log_file.read_bytes()
    log_file.write_bytes(b"")
    backup.write_bytes(content)
    # Ältestes Backup löschen
    oldest = LOG_DIR / f"cron.log.{MAX_FILES + 1}"
    if oldest.exists():
        oldest.unlink()


# ── API-Aufruf ────────────────────────────────────────────────────────────────

def build_api_url(ip4: Optional[str], ip6: Optional[str], ipv6_active: bool) -> str:
    url = f"https://ipv64.net/nic/update?key={DOMAIN_KEY}&domain={DOMAIN_IPV64}"
    if DOMAIN_PRAEFIX_YES and DOMAIN_PRAEFIX:
        url += f"&praefix={DOMAIN_PRAEFIX}"
    if IPV4_ENABLED and ip4:
        url += f"&ip={ip4}"
    if ipv6_active and ip6:
        url += f"&ip6={ip6}"
    url += "&output=min"
    return url


def call_api(ip4: Optional[str], ip6: Optional[str], ipv6_active: bool) -> str:
    url = build_api_url(ip4, ip6, ipv6_active)
    masked = url.replace(DOMAIN_KEY, "****") if DOMAIN_KEY else url
    log_info(f"API Call: {masked}")
    try:
        resp = _session().get(url, timeout=15)
        return resp.text.strip()
    except Exception as e:
        log_error(f"API Call fehlgeschlagen: {e}")
        return ""


# ── Haupt-Update-Logik ────────────────────────────────────────────────────────

def run_update(first_run: bool = False) -> bool:
    """
    Führt einen kompletten DDNS-Update-Zyklus durch.
    Gibt True zurück bei Erfolg oder wenn kein Update nötig war.
    Gibt False zurück bei Konfigurations- oder Netzwerkfehler.
    """
    domains = [d.strip() for d in DOMAIN_IPV64.split(",") if d.strip()]

    # IPv6-System-Verfügbarkeit prüfen
    ipv6_active = IPV6_ENABLED
    if ipv6_active:
        if check_ipv6_system():
            log_info("IPv6 ist verfügbar und aktiviert")
        else:
            log_warn("IPv6 ist im System nicht verfügbar, deaktiviere IPv6-Funktionalität")
            log_info("IPv6_ENABLED wird automatisch auf 'no' gesetzt")
            ipv6_active = False

    # Netzwerk-Check
    if NETWORK_CHECK and not network_check():
        log_sep()
        return False

    # IPs erkennen
    ip4 = detect_ipv4() if IPV4_ENABLED else None
    ip6 = detect_ipv6() if ipv6_active else None

    if not ip4 and not ip6:
        log_error("Keine IP-Adresse (IPv4 oder IPv6) gefunden")
        log_sep()
        return False

    # Gespeicherten Zustand lesen
    stored_ip4, stored_ip6 = read_state()

    # Prüfen ob Update nötig ist
    update_needed = False
    if ip4 and ip4 != stored_ip4:
        update_needed = True
        log_upd(f"IPv4 UPDATE ERFORDERLICH - Aktuelle={ip4}  Alte={stored_ip4 or 'keine'}")
    if ip6 and ip6 != stored_ip6:
        update_needed = True
        log_upd(f"IPv6 UPDATE ERFORDERLICH - Aktuelle={ip6}  Alte={stored_ip6 or 'keine'}")

    if not update_needed and not first_run:
        log_info(
            f"KEIN UPDATE - "
            f"IPv4={ip4 or 'deaktiviert'}  "
            f"IPv6={ip6 or 'deaktiviert'}"
        )
        log_sep()
        return True

    # ── Rate-Limiter prüfen ───────────────────────────────────────────────────
    limiter = RateLimiter()
    allowed, count = limiter.is_allowed()

    if not allowed:
        log_rate(
            f"Limit erreicht: {count}/{RATE_LIMIT_MAX_UPDATES} Updates "
            f"in den letzten {RATE_LIMIT_WINDOW_MINUTES} Minuten – Update übersprungen"
        )
        log_rate(
            f"Nächstes Update möglich wenn ältester Eintrag "
            f"älter als {RATE_LIMIT_WINDOW_MINUTES} Min. ist"
        )
        if NOTIFY_URL:
            domain_list = ", ".join(
                f"{DOMAIN_PRAEFIX}.{d}" if DOMAIN_PRAEFIX_YES and DOMAIN_PRAEFIX else d
                for d in domains
            )
            send_notification(
                title="⚠️ DDNS Rate-Limit erreicht",
                message=(
                    f"Updates: {count}/{RATE_LIMIT_MAX_UPDATES} "
                    f"in {RATE_LIMIT_WINDOW_MINUTES} Min.\n"
                    f"Domains: {domain_list}\n"
                    f"Update wurde übersprungen."
                ),
            )
        log_sep()
        return True  # Kein Fehler, nur gedrosselt

    # ── API-Aufruf ────────────────────────────────────────────────────────────
    log_upd("Sende Update an ipv64.net...")
    if ip4:
        log_upd(f"Update IPv4={ip4}  Alte-IPv4={stored_ip4 or 'keine'}")
    if ip6:
        log_upd(f"Update IPv6={ip6}  Alte-IPv6={stored_ip6 or 'keine'}")

    response = call_api(ip4, ip6, ipv6_active)

    if any(r in response.lower() for r in SUCCESS_RESPONSES):
        # ── Erfolg ────────────────────────────────────────────────────────────
        log_upd("UPDATE ERFOLGREICH AN IPV64.NET GESENDET")
        if ip4:
            log_upd(f"IPv4 {ip4} wurde aktualisiert")
        if ip6:
            log_upd(f"IPv6 {ip6} wurde aktualisiert")

        # Rate-Limiter: Timestamp speichern
        limiter.record_update()

        # State speichern
        write_state(ip4, ip6)

        # DNS-Einträge nach Update prüfen
        if IP_CHECK:
            import time
            time.sleep(5)
            run_dns_check()
            return True  # dns_check druckt bereits log_sep()

        # Benachrichtigung
        if NOTIFY_URL:
            domain_list = "\n".join(
                f"Domain: {DOMAIN_PRAEFIX}.{d}" if DOMAIN_PRAEFIX_YES and DOMAIN_PRAEFIX
                else f"Domain: {d}"
                for d in domains
            )
            send_notification(
                title="🟢 DDNS Update erfolgreich",
                message=(
                    f"{f'IPv4: {ip4}' if ip4 else ''}\n"
                    f"{f'IPv6: {ip6}' if ip6 else ''}\n"
                    f"{domain_list}"
                ).strip(),
            )

        log_sep()
        return True

    else:
        # ── Fehler ────────────────────────────────────────────────────────────
        if "Updateintervall" in response:
            log_error("Dein DynDNS Update Limit ist wohl erreicht (Server-seitig)")
            log_info(
                "Es kann erst wieder ein Update gesendet werden, "
                "wenn dein DynDNS Update Limit im grünen Bereich ist"
            )
        elif first_run:
            log_error("Die Angaben sind falsch gesetzt: DOMAIN oder DOMAIN KEY")
            log_info(
                "Stoppen Sie den Container und starten Sie ihn "
                "mit den richtigen Angaben erneut"
            )
            log_sep()
            return False
        else:
            log_error(f"UPDATE WURDE NICHT AN IPV64.NET GESENDET – Response: {response!r}")

        # Benachrichtigung bei Fehler
        if NOTIFY_URL:
            domain_list = ", ".join(domains)
            send_notification(
                title="🔴 DDNS Update fehlgeschlagen",
                message=(
                    f"{f'IPv4: {ip4}' if ip4 else ''}\n"
                    f"Server Response: {response}\n"
                    f"Domains: {domain_list}"
                ).strip(),
            )

        log_sep()
        return "Updateintervall" not in response


# ── Entry Point ───────────────────────────────────────────────────────────────

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="DDNS Updater für ipv64.net")
    parser.add_argument(
        "--first-run",
        action="store_true",
        help="Erster Start: Credentials validieren und Update erzwingen",
    )
    parser.add_argument(
        "--dns-check",
        action="store_true",
        help="Nur aktuelle DNS-Einträge loggen (kein Update)",
    )
    args = parser.parse_args()

    if args.dns_check:
        run_dns_check()
        sys.exit(0)

    # Log-Rotation bei normalem Lauf
    if not args.first_run:
        rotate_log()

    success = run_update(first_run=args.first_run)
    sys.exit(0 if success else 1)
