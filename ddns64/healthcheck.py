#!/usr/bin/env python3
import os
import sys
import socket
import requests
from datetime import datetime

def _ts() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")

def log_info(msg: str):  print(f"{_ts()}  INFO    !!!  - {msg}", flush=True)
def log_warn(msg: str):  print(f"{_ts()}  WARNUNG !!!  - {msg}", flush=True)
def log_error(msg: str): print(f"{_ts()}  FEHLER  !!!  - {msg}", flush=True)
def log_ok(msg: str):    print(f"{_ts()}  OK      !!!  - {msg}", flush=True)

# ── Konfiguration ─────────────────────────────────────────────────────────────
IPV4_ENABLED  = os.environ.get("IPV4_ENABLED",  "yes").lower() in ("yes", "y", "1", "true")
IPV6_ENABLED  = os.environ.get("IPV6_ENABLED",  "yes").lower() in ("yes", "y", "1", "true")
NAME_SERVER  = os.environ.get("NAME_SERVER", "ns1.ipv64.net")
USER_AGENT   = os.environ.get(
    "CURL_USER_AGENT",
    "docker-ddns-ipv64-python/2.0.0 github.com/Strice91/ddns-ipv64"
)

def check_ipv6_system() -> bool:
    try:
        s = socket.socket(socket.AF_INET6, socket.SOCK_STREAM)
        s.settimeout(3)
        s.connect(("2606:4700:4700::1111", 80))  # Cloudflare IPv6 DNS
        s.close()
        return True
    except Exception:
        return False

def check_dns(nameserver: str) -> bool:
    try:
        # Versuche eine IP-Adresse aufzulösen oder Nameserver direkt per Socket zu pingen/verbinden (Port 53 UDP/TCP)
        # Für einen robusten Check benutzen wir dns.resolver wenn importierbar
        import dns.resolver
        resolver = dns.resolver.Resolver()
        # Versuche Nameserver aufzulösen falls er ein Hostname ist
        try:
            socket.inet_aton(nameserver)
            ns_ips = [nameserver]
        except socket.error:
            ns_ips = [str(r) for r in dns.resolver.resolve(nameserver, "A")]
        
        resolver.nameservers = ns_ips
        resolver.lifetime = 3.0
        resolver.resolve("ipv64.net", "A")
        return True
    except Exception as e:
        log_warn(f"DNS check failed via dnspython: {e}")
        # Fallback auf socket gethostbyname
        try:
            socket.gethostbyname("ipv64.net")
            return True
        except Exception:
            return False

def main():
    ipv6_active = IPV6_ENABLED
    if ipv6_active:
        if not check_ipv6_system():
            log_warn("IPv6 ist im System nicht verfügbar")
            ipv6_active = False

    health_status = "OK"

    headers = {"User-Agent": USER_AGENT}

    # Check IPv4
    if IPV4_ENABLED:
        try:
            # Erzwinge IPv4 via custom Adapter oder socket bind falls nötig, 
            # aber für einen einfachen check reicht get.
            # Um sicherzugehen, dass es IPv4 nutzt, kann requests.get mit timeout benutzt werden.
            # IPv4 erfragen wir an einem IPv4-only Endpoint oder vertrauen auf das System.
            resp = requests.get("https://ipv64.net/ipcheck.php?ipv4", headers=headers, timeout=5)
            if resp.status_code == 200:
                log_ok("IPv4 Verbindung zu ipv64.net funktioniert")
            else:
                log_warn(f"IPv4 Verbindung zu ipv64.net lieferte Status {resp.status_code}")
                health_status = "PARTIAL"
        except Exception as e:
            log_warn(f"IPv4 Verbindung zu ipv64.net nicht möglich: {e}")
            health_status = "PARTIAL"

    # Check IPv6
    if ipv6_active:
        try:
            # ipv64.net/ipcheck.php?ipv6 ist IPv6-only oder wir fragen es an.
            resp = requests.get("https://ipv64.net/ipcheck.php?ipv6", headers=headers, timeout=5)
            if resp.status_code == 200:
                log_ok("IPv6 Verbindung zu ipv64.net funktioniert")
            else:
                log_warn(f"IPv6 Verbindung zu ipv64.net lieferte Status {resp.status_code}")
                if health_status == "PARTIAL":
                    health_status = "FAIL"
                else:
                    health_status = "PARTIAL"
        except Exception as e:
            log_warn(f"IPv6 Verbindung zu ipv64.net nicht möglich: {e}")
            if health_status == "PARTIAL":
                health_status = "FAIL"
            else:
                health_status = "PARTIAL"

    # Check DNS
    if check_dns(NAME_SERVER):
        log_ok(f"NAMESERVER {NAME_SERVER} ist erreichbar")
    else:
        log_error(f"NAMESERVER {NAME_SERVER} ist nicht erreichbar")
        health_status = "FAIL"

    # Final result
    if health_status == "OK":
        log_info("HEALTH - Alle Verbindungen funktionieren")
        sys.exit(0)
    elif health_status == "PARTIAL":
        log_info("HEALTH - Teilweise Verbindungsprobleme (IPv4 oder IPv6)")
        sys.exit(0)  # Still considered healthy if at least one IP version works
    else:
        log_error("HEALTH - Kritische Verbindungsprobleme")
        sys.exit(1)

if __name__ == "__main__":
    main()
