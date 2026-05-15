#!/usr/bin/env python3
"""Safe mock updater CLI for local testing. It never modifies files or reboots."""
from __future__ import annotations

import argparse
import json
import sys

from mock_shared import check_for_updates_mock, load_update_state, mock_autoupdate, mock_install_update_blocked, save_update_state, set_mock_pending_update


def print_json(data):
    print(json.dumps(data, indent=2, sort_keys=True))


def main() -> int:
    parser = argparse.ArgumentParser(description="MementoFrame mock updater")
    parser.add_argument("command", choices=["status", "check", "update", "autoupdate", "install", "diagnose", "pending-on", "pending-off"])
    args = parser.parse_args()
    if args.command == "status":
        print_json(load_update_state())
    elif args.command == "check":
        print_json(check_for_updates_mock())
    elif args.command in {"update", "install"}:
        print_json(mock_install_update_blocked())
    elif args.command == "autoupdate":
        print_json(mock_autoupdate())
    elif args.command == "pending-on":
        print_json(set_mock_pending_update(True))
    elif args.command == "pending-off":
        print_json(set_mock_pending_update(False))
    elif args.command == "diagnose":
        state = load_update_state()
        print_json({"mock": True, "message": "Mock updater is installed and safe; update/install/reboot are disabled.", "state": state})
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
