#!/usr/bin/env python3
import os
import sys
import time
import subprocess
from pathlib import Path

DATA_DIR = Path(os.environ.get("DATA_DIR", "/data"))
LOG_DIR = DATA_DIR / "log"
STATE_IPV4 = DATA_DIR / "updip.txt"
STATE_IPV6 = DATA_DIR / "updip6.txt"

def log_info(msg: str):  print(f"{time.strftime('%Y-%m-%d %H:%M:%S')}  INFO    !!!  - {msg}", flush=True)
def log_warn(msg: str):  print(f"{time.strftime('%Y-%m-%d %H:%M:%S')}  WARNUNG !!!  - {msg}", flush=True)
def log_error(msg: str): print(f"{time.strftime('%Y-%m-%d %H:%M:%S')}  FEHLER  !!!  - {msg}", flush=True)
def log_ok(msg: str):    print(f"{time.strftime('%Y-%m-%d %H:%M:%S')}  OK      !!!  - {msg}", flush=True)


def setup_permissions():
    puid = os.environ.get("PUID", "0")
    pgid = os.environ.get("PGID", "0")
    
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    (LOG_DIR / "cron.log").touch(exist_ok=True)
    
    if puid != "0" or pgid != "0":
        try:
            uid = int(puid)
            gid = int(pgid)
            log_info(f"Setze Berechtigungen für {DATA_DIR} auf UID={uid}, GID={gid}")
            os.chown(DATA_DIR, uid, gid)
            for path in DATA_DIR.rglob("*"):
                try:
                    os.chown(path, uid, gid)
                except Exception as e:
                    log_warn(f"Konnte Berechtigung für {path} nicht ändern: {e}")
        except Exception as e:
            log_error(f"Fehler beim Setzen der PUID/PGID: {e}")

def validate_config():
    valid = True
    domain_key = os.environ.get("DOMAIN_KEY", "")
    domain_ipv64 = os.environ.get("DOMAIN_IPV64", "")
    cron_time = os.environ.get("CRON_TIME", "")
    cron_time_dig = os.environ.get("CRON_TIME_DIG", "")
    
    if not domain_key:
        log_error("Sie haben keinen DOMAIN Key gesetzt (DOMAIN_KEY)")
        valid = False
    if not domain_ipv64:
        log_error("Sie haben keine DOMAIN gesetzt (DOMAIN_IPV64)")
        valid = False
    if not cron_time:
        log_error("Sie haben kein CRON_TIME gesetzt")
        valid = False
    if not cron_time_dig:
        log_error("Sie haben kein CRON_TIME_DIG gesetzt")
        valid = False
        
    if not valid:
        log_error("Konfiguration ungültig. Container wartet unendlich...")
        while True:
            time.sleep(3600)

def check_notifications():
    notify_url = os.environ.get("NOTIFY_URL", "")
    skip_test = os.environ.get("NOTIFY_SKIP_TEST", "no").lower() in ("yes", "y", "1", "true")
    if notify_url:
        if skip_test:
            log_info("Shoutrrr/Apprise Testnachricht übersprungen (NOTIFY_SKIP_TEST=yes)")
            return
        
        log_info("Sende Shoutrrr/Apprise Testnachricht...")
        try:
            import apprise
            ap = apprise.Apprise()
            ap.add(notify_url)
            success = ap.notify(
                title="🟢 DDNS Updater Test",
                body="DDNS Updater in Docker für Free DynDNS IPv64.net gestartet."
            )
            if success:
                log_ok("Testnachricht erfolgreich gesendet")
            else:
                log_error("Fehler beim Senden der Testnachricht (Apprise returned False)")
        except Exception as e:
            log_error(f"Fehler beim Senden der Testnachricht: {e}")

def run_first_run():
    firstrun_file = Path("/etc/.firstrun")
    if firstrun_file.exists():
        log_info("Erster Start: Führe initiales Update aus...")
        try:
            # Führe ddns_updater.py mit --first-run aus
            res = subprocess.run([sys.executable, "/app/ddns_updater.py", "--first-run"])
            if res.returncode == 0:
                firstrun_file.unlink(missing_ok=True)
                log_ok("Initiales Update erfolgreich abgeschlossen")
            else:
                log_error("Initiales Update fehlgeschlagen. Versuche es beim nächsten Cron-Lauf erneut.")
        except Exception as e:
            log_error(f"Fehler beim ersten Lauf: {e}")

def setup_cron():
    cron_time = os.environ.get("CRON_TIME", "*/15 * * * *")
    cron_time_dig = os.environ.get("CRON_TIME_DIG", "*/30 * * * *")
    ip_check = os.environ.get("IP_CHECK", "yes").lower() in ("yes", "y", "1", "true")
    
    cron_lines = [
        f"{cron_time} {sys.executable} /app/ddns_updater.py >> /data/log/cron.log 2>&1"
    ]
    if ip_check:
        cron_lines.append(
            f"{cron_time_dig} {sys.executable} /app/ddns_updater.py --dns-check >> /data/log/cron.log 2>&1"
        )
        
    cron_content = "\n".join(cron_lines) + "\n"
    
    cron_dir = Path("/etc/cron.d")
    cron_dir.mkdir(parents=True, exist_ok=True)
    cron_file = cron_dir / "container_cronjob"
    cron_file.write_text(cron_content)
    
    # Crontab laden
    subprocess.run(["crontab", str(cron_file)], check=True)
    log_info("Cronjobs erfolgreich eingerichtet")

def start_crond():
    log_info("Starte crond...")
    subprocess.Popen(["crond"])

def main():
    setup_permissions()
    validate_config()
    check_notifications()
    setup_cron()
    run_first_run()
    start_crond()



if __name__ == "__main__":
    main()
