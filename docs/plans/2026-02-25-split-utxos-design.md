# `split_utxos` Tool Design

## Goal

Add a `split_utxos` tool to the utxo-bundle that splits wallet funds into discrete UTXOs of user-specified sizes via Bitcoin Core's `send` RPC.

## Background

The utxo-bundle already provides a `list_utxos` tool that queries Bitcoin Core via JSON-RPC (httpx). Users need a way to split wallet funds into multiple UTXOs of specific denominations for testing, privacy, or coin management workflows. Today this requires manual transaction construction; a dedicated tool automates the entire flow.

## Approach

Single `split_utxos` tool added to the existing `tool-bitcoin-rpc` module. The tool uses Bitcoin Core's `send` RPC (available since v0.21+, node runs v28+), which handles coin selection, change, signing, and broadcast in one call. This avoids reimplementing any wallet logic and keeps the tool minimal.

## Architecture

One new `SplitUtxosTool` class alongside the existing `ListUtxosTool`. Both tools share RPC credentials, URL, and the same class pattern. The `mount()` function registers both with the coordinator.

```
tool-bitcoin-rpc/
  amplifier_module_tool_bitcoin_rpc/
    __init__.py          # ListUtxosTool + SplitUtxosTool + mount()
  context/
    instructions.md      # Updated with split workflow guidance
```

## Tool Interface

```yaml
name: split_utxos
description: >
  Split wallet funds into discrete UTXOs of specified sizes.
  Generates new wallet addresses (or accepts external addresses),
  builds the transaction via Bitcoin Core's send RPC,
  and broadcasts it. Change is automatically sent to a
  wallet-generated change address by Bitcoin Core.

input_schema:
  type: object
  properties:
    outputs:
      type: array
      description: "List of output specifications"
      items:
        type: object
        properties:
          amount_sats:
            type: integer
            description: "Amount in satoshis for each UTXO"
          count:
            type: integer
            description: "Number of UTXOs at this amount"
          address:
            type: string
            description: "Optional external address. If omitted, getnewaddress is called for each output."
        required: [amount_sats, count]
    wallet:
      type: string
      description: "Named wallet. Omit for default wallet."
  required: [outputs]
```

### Example Input

"Generate 6 UTXOs: 2 at 2k sats, 2 at 4k sats, 2 at 8k sats":

```json
{
  "outputs": [
    {"amount_sats": 2000, "count": 2},
    {"amount_sats": 4000, "count": 2},
    {"amount_sats": 8000, "count": 2}
  ]
}
```

## Execution Flow

1. Parse `outputs` array from input.
2. For each output entry:
   - If `address` is provided: use it (repeated `count` times).
   - If no `address`: call `getnewaddress` RPC once per output to generate a unique address.
3. Build the outputs map (`{address: btc_amount, ...}`):
   - Convert sats to BTC: `amount_sats / 100_000_000`.
   - Each output gets its own unique address.
4. Call `send` RPC with `[outputs_map]`.
   - Bitcoin Core handles: coin selection, change address, signing, broadcast.
5. Return: txid + table of (address, amount_sats) for each created output.

## Output Format

On success:

```
Transaction broadcast: <txid>

Created 6 UTXOs:

  1.  2,000 sats  ->  bcrt1q...abc1
  2.  2,000 sats  ->  bcrt1q...abc2
  3.  4,000 sats  ->  bcrt1q...def1
  4.  4,000 sats  ->  bcrt1q...def2
  5.  8,000 sats  ->  bcrt1q...ghi1
  6.  8,000 sats  ->  bcrt1q...ghi2

Change returned to wallet automatically.
```

## Error Handling

| Error Case | Handling |
|---|---|
| Insufficient funds | Catch RPC error, report total needed vs available |
| Invalid external address | Catch RPC validation error, report which address failed |
| Node unreachable | Same httpx error handling pattern as existing `list_utxos` |

## Implementation Details

- New `SplitUtxosTool` class in `modules/tool-bitcoin-rpc/amplifier_module_tool_bitcoin_rpc/__init__.py`.
- Follows the exact same class pattern as `ListUtxosTool`: same constructor args, same `name`/`description`/`input_schema` properties, same `execute` async method.
- `mount()` function updated to register both tools with the coordinator.
- Shared RPC credentials and URL between both tools.
- `context/instructions.md` expanded to teach the agent about split workflows -- how to interpret natural language UTXO split requests and translate them into the correct `outputs` array.

## Scope Boundaries

- **Block mining** is not handled by this tool. Users mine blocks separately after the transaction is broadcast.
- **Fee estimation** is delegated entirely to Bitcoin Core's defaults via the `send` RPC.
- **Change management** is automatic -- Bitcoin Core sends change to a wallet-generated address.

## Open Questions

None. All design decisions have been confirmed.
