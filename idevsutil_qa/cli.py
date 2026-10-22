from __future__ import annotations

import argparse
import os

from .console import Console


def parse_args():
    parser = argparse.ArgumentParser(
        description="Automate idevsutil incremental backup/version restore tests."
    )

    parser.add_argument(
        "--exe",
        default="",
        help=r"Path to idevsutil executable, e.g. C:\...\idwutil_600.exe",
    )
    parser.add_argument("--user", required=True)
    parser.add_argument("--server", required=True)
    parser.add_argument("--device-id", help="Omit if the account is non dedup")
    parser.add_argument("--server-root")
    parser.add_argument("--password", required=True)
    parser.add_argument(
        "--port", default=0, help="Omit when not running on test machine."
    )

    parser.add_argument("--dedup", required=True, help="Dedup 1. Non-Dedup 0")

    parser.add_argument(
        "--pvt-key",
        default=None,
        help="Private encryption key file. Omit when default encryption is used.",
    )

    parser.add_argument(
        "--sync-dedup",
        default=0,
        help="Over Rides Dedup",
    )

    parser.add_argument(
        "--remote-root",
        default="home/",
        help="Remote root. Default: home/",
    )

    if os.name == "nt":
        parser.add_argument(
            "--workspace",
            default="F:/QA/QA-21-10-2026",
            help="Local workspace directory.",
        )
    else:
        parser.add_argument(
            "--workspace",
            default="/home/sandeep/QA/TLS-Tunnel-22-10-2026",
            help="Local workspace directory.",
        )

    parser.add_argument(
        "--timeout",
        type=int,
        default=3600,
        help="Command timeout in seconds.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Generate files/commands but do not execute idevsutil.",
    )

    parser.add_argument(
        "--utf8-cmd",
        type=int,
        default=0,
        help="Pass INT 1 to use UTF8-Encryption. Default 0",
    )
    if os.name == "nt":
        parser.add_argument("--fileListPath", default="F:/QA/QA-24-9-2026/filelist.txt")
    else:
        parser.add_argument("--fileListPath", default="/home/sandeep/filelist.txt")
    return parser.parse_args()


def main():
    args = parse_args()
    console = Console()
    console.configure(args)
    console.run()
