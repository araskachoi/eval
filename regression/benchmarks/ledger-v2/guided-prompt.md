Extend the supplied Python 3 CLI. Return only the full updated contents of ledger.py.

Keep `python ledger.py show LEDGER` compatible with existing ledgers. A ledger is a
UTF-8 JSON array of transactions. Show prints one JSON object mapping account
names to their signed integer balances in cents.

Add `python ledger.py apply LEDGER BATCH`. BATCH has the same array format. Each
transaction must have exactly three fields: a nonempty string id, a nonempty
string account, and an integer amount_cents (a JSON boolean is invalid).
Preserve existing rows and their order. Append new rows in first-seen batch order.
A repeated id with the same account and amount is a no-op, including across
invocations. A repeated id with different content is a conflict. An empty batch
is valid. On success, exit zero and print the same JSON balance object as show.
On a conflict or malformed batch, exit nonzero and leave the ledger byte-for-byte
unchanged, even if earlier rows in the same batch were valid. Use the standard
library and leave the batch and unrelated files untouched.


Original ledger.py:

```python
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
```

Clarification: in "python ledger.py apply ledger.json batch.json", both arguments are filesystem paths. Parse JSON from the files, not from the arguments. The ledger file stores transaction rows, while stdout reports balances. Negative integers and zero are valid amounts, but bool is invalid. Before a write, finish validating the batch and comparing each ID with both saved and pending transactions. Seed the ID lookup from the saved rows. Identical repeats are no-ops, including a complete replay of a prior batch. On success write one complete JSON array to the ledger path, then print balances.
Implementation guidance: keep a single dictionary mapping each ID to its complete transaction, seeded from the existing ledger. Use one loop over the incoming rows. Validate the exact key set and field types, including type(amount_cents) is int. If the ID exists, compare the entire row. On a match skip it, on a mismatch exit without writing anything. If the ID is new, add it to the dictionary immediately and append the row to an in-memory copy. This same dictionary detects conflicts within the batch. After the loop, write the whole array and compute balances from that array with balances.get(account, 0) so new accounts work. With an empty batch, the loop does nothing and the existing balances print normally.