"""Starter CLI for the ledger benchmark."""
import argparse
import json
from pathlib import Path


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=["show"])
    parser.add_argument("ledger", type=Path)
    args = parser.parse_args()
    balances = {}
    for row in json.loads(args.ledger.read_text()):
        account = row["account"]
        balances[account] = balances.get(account, 0) + row["amount_cents"]
    print(json.dumps(balances, sort_keys=True))


if __name__ == "__main__":
    main()
