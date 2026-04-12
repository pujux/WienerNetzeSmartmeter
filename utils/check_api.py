"""
Quick script to manually inspect live API responses.
Credentials are read interactively from stdin.
Usage:
    python utils/check_api.py
    python utils/check_api.py --command bewegungsdaten
    python utils/check_api.py --command history
"""
import argparse
import getpass
import json
import sys
import os
from datetime import datetime, timedelta, date

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'custom_components'))

from wnsm.api.client import Smartmeter
from wnsm.api.constants import ValueType

COMMANDS = ['zaehlpunkte', 'bewegungsdaten', 'history']


def pp(data):
    print(json.dumps(data, indent=2, default=str))


def main():
    parser = argparse.ArgumentParser(description='Check live Wiener Netze API responses')
    parser.add_argument('--command', choices=COMMANDS, default='zaehlpunkte',
                        help=f'What to query: {COMMANDS}')
    parser.add_argument('--zaehlpunkt', default=None,
                        help='Zaehlpunktnummer (optional, uses first active one if omitted)')
    parser.add_argument('--days', type=int, default=30,
                        help='How many days back to query (for bewegungsdaten/history)')
    parser.add_argument('--granularity', choices=['QUARTER_HOUR', 'DAY'], default='DAY',
                        help='Granularity for bewegungsdaten')
    args = parser.parse_args()

    username = input("Username: ")
    password = getpass.getpass("Password: ")

    sm = Smartmeter(username=username, password=password)
    print(f"Logging in as {username}...")
    sm.login()
    print("Login successful.\n")

    if args.command == 'zaehlpunkte':
        print("=== Zaehlpunkte ===")
        pp(sm.zaehlpunkte())

    elif args.command == 'bewegungsdaten':
        date_until = date.today()
        date_from = date_until - timedelta(days=args.days)
        granularity = ValueType[args.granularity]
        print(f"=== Bewegungsdaten ({args.granularity}, {date_from} -> {date_until}) ===")
        pp(sm.bewegungsdaten(args.zaehlpunkt, date_from, date_until, granularity))

    elif args.command == 'history':
        date_until = date.today()
        date_from = date_until - timedelta(days=args.days)
        print(f"=== Historical data ({date_from} -> {date_until}) ===")
        pp(sm.historical_data(args.zaehlpunkt, date_from, date_until))


if __name__ == '__main__':
    main()
