"""
Web Control Panel Launcher
===========================
Interactive startup that asks for port and access permission, then starts
the Flask web server.

Usage:
    python run_web.py
    (run as Administrator for automatic firewall rule creation)
"""

import ipaddress
import socket
import subprocess
import sys
from pathlib import Path

TOOLKIT_DIR = Path(__file__).resolve().parent / "agent-skill-toolkit"

_FIREWALL_RULE_NAME = "Agent Skill Toolkit Web Panel"


def _get_lan_ip() -> str:
    """Detect the primary LAN IP address of this machine."""
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.settimeout(0.1)
        s.connect(("10.255.255.255", 1))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except OSError:
        return "127.0.0.1"


def _get_all_ips() -> list[str]:
    """Return all non-loopback IPv4 addresses for this machine."""
    ips: list[str] = []
    try:
        hostname = socket.gethostname()
        for info in socket.getaddrinfo(hostname, None, socket.AF_INET):
            ip = info[4][0]
            if ip != "127.0.0.1" and ip not in ips:
                ips.append(ip)
    except Exception:
        pass
    lan = _get_lan_ip()
    if lan != "127.0.0.1" and lan not in ips:
        ips.append(lan)
    return ips


def _is_private_ip(ip_str: str) -> bool:
    """Check whether an IP string belongs to a private / LAN range."""
    try:
        return ipaddress.ip_address(ip_str).is_private
    except ValueError:
        return False


def _open_firewall(port: int) -> bool:
    """Add a Windows Firewall inbound rule for *port*.
    Returns True on success, False if the user needs to do it manually.
    Requires Administrator privileges.
    """
    if sys.platform != "win32":
        return True  # non-Windows — assume no firewall issue

    # Check if the rule already exists
    check = subprocess.run(
        ["netsh", "advfirewall", "firewall", "show", "rule",
         f"name={_FIREWALL_RULE_NAME}"],
        capture_output=True, text=True,
    )
    if check.returncode == 0 and f"LocalPort:\t{port}" in check.stdout.replace(" ", ""):
        print(f"  Firewall rule already exists for port {port}.")
        return True

    # Try to add the rule
    print(f"  Adding Windows Firewall rule for port {port} ...")
    result = subprocess.run(
        ["netsh", "advfirewall", "firewall", "add", "rule",
         f"name={_FIREWALL_RULE_NAME}",
         "dir=in", "action=allow", "protocol=TCP",
         f"localport={port}"],
        capture_output=True, text=True,
    )

    if result.returncode == 0:
        print(f"  Firewall rule added successfully.")
        return True

    # Failed — likely not running as Administrator
    if "requires elevation" in result.stderr.lower() or "access is denied" in result.stderr.lower():
        print()
        print("  ⚠  Could not add firewall rule — Administrator privileges required.")
        print(f"  Run this once manually as Administrator:")
        print(f'    netsh advfirewall firewall add rule name="{_FIREWALL_RULE_NAME}" dir=in action=allow protocol=TCP localport={port}')
        print()
    else:
        print(f"  Firewall rule creation failed: {result.stderr.strip()}")
    return False


def main() -> None:
    print()
    print("=" * 56)
    print("  Agent Skill Toolkit — Web Control Panel Launcher")
    print("=" * 56)
    print()

    # ── Port ──────────────────────────────────────────────────────────
    while True:
        raw = input("  Port number [5000]: ").strip()
        if not raw:
            port = 5000
            break
        try:
            port = int(raw)
            if 1 <= port <= 65535:
                break
            print("  ! Port must be between 1 and 65535")
        except ValueError:
            print("  ! Please enter a valid number")

    # ── Access permission ─────────────────────────────────────────────
    lan_ip = _get_lan_ip()
    print()
    print("  Access permission:")
    print("    [1] Local only       (127.0.0.1)")
    if lan_ip != "127.0.0.1":
        print(f"    [2] LAN only         ({lan_ip} — current subnet)")
    else:
        print("    [2] LAN only         (no LAN IP detected)")
    print("    [3] All interfaces   (0.0.0.0 — WARNING: accessible from anywhere)")
    print()

    while True:
        choice = input("  Choose [1/2/3, default=1]: ").strip() or "1"
        if choice == "1":
            host = "127.0.0.1"
            access_label = "local only"
            break
        elif choice == "2":
            host = "0.0.0.0"
            access_label = "LAN only (IP filter)"
            break
        elif choice == "3":
            print()
            print("  !! WARNING: 0.0.0.0 exposes the control panel to the entire")
            print("  !! network AND the internet (if not firewalled). Anyone who")
            print("  !! can reach this port can attempt to log in.")
            confirm = input("\n  Type 'yes' to confirm: ").strip()
            if confirm.lower() == "yes":
                host = "0.0.0.0"
                access_label = "all interfaces"
                break
            print("  Cancelled.")
            continue
        else:
            print("  ! Please enter 1, 2, or 3")

    # ── Firewall (non-localhost modes) ────────────────────────────────
    if host != "127.0.0.1":
        print()
        _open_firewall(port)

    # ── Import and configure the web panel ────────────────────────────
    if str(TOOLKIT_DIR) not in sys.path:
        sys.path.insert(0, str(TOOLKIT_DIR))

    import web_panel  # pyright: ignore[reportMissingImports]

    # Inject LAN-only IP filter for option 2
    if choice == "2":
        app_ref = web_panel.app

        @app_ref.before_request
        def _lan_only_filter():
            from flask import abort, request
            client_ip = request.remote_addr or "127.0.0.1"
            if client_ip in ("127.0.0.1", "::1"):
                return None
            if _is_private_ip(client_ip):
                return None
            abort(403)

        print("  LAN filter active — only private-range IPs + localhost allowed.")

    # ── Print access URLs ─────────────────────────────────────────────
    print(f"\n  Starting web control panel...")
    print(f"  Access mode: {access_label}")
    print(f"  Password:    (set in config.py → WEB_PANEL_PASSWORD)")

    if host == "127.0.0.1":
        print(f"  URL:         http://127.0.0.1:{port}")
    else:
        print(f"  Local URL:   http://127.0.0.1:{port}")
        if lan_ip != "127.0.0.1":
            print(f"  LAN URL:     http://{lan_ip}:{port}")
        for ip in [ip for ip in _get_all_ips() if ip != lan_ip]:
            print(f"              http://{ip}:{port}")

    print()

    web_panel.run_server(host=host, port=port)


if __name__ == "__main__":
    main()
