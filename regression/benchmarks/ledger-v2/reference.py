"""Reference submission for isolated regression verification."""
import argparse
import json
from pathlib import Path
from tempfile import NamedTemporaryFile


def apply(ledger, rows, batch):
    incoming = json.loads(batch.read_text())
    if not isinstance(incoming, list):
        raise ValueError('Expected transaction list')
    by_id = {row['id']: row for row in rows}
    for row in incoming:
        if (not isinstance(row, dict) or set(row) != {'id', 'account', 'amount_cents'}
                or not isinstance(row['id'], str) or not row['id']
                or not isinstance(row['account'], str) or not row['account']
                or type(row['amount_cents']) is not int):
            raise ValueError('Invalid transaction')
        previous = by_id.get(row['id'])
        if previous is None:
            by_id[row['id']] = row
            rows.append(row)
        elif previous != row:
            raise ValueError('Conflicting transaction')
    with NamedTemporaryFile(mode='w', dir=ledger.parent, delete_on_close=False) as output:
        json.dump(rows, output)
        output.close()
        Path(output.name).replace(ledger)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('command', choices=['show', 'apply'])
    parser.add_argument('ledger', type=Path)
    parser.add_argument('batch', type=Path, nargs='?')
    args = parser.parse_args()
    rows = json.loads(args.ledger.read_text())
    if args.command == 'apply':
        try:
            apply(args.ledger, rows, args.batch)
        except (ValueError, OSError) as exc:
            parser.exit(1, str(exc))
    balances = {}
    for row in rows:
        account = row['account']
        balances[account] = balances.get(account, 0) + row['amount_cents']
    print(json.dumps(balances, sort_keys=True))


if __name__ == '__main__':
    main()
