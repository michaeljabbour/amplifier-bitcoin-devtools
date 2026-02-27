# utxo-bundle

An [Amplifier](https://github.com/microsoft/amplifier) bundle for Bitcoin
Core wallet management, Lightning Network operations, and [Aggeus prediction
markets](https://supertestnet.github.io/aggeus_market/diagram.html) against local development nodes (regtest/signet via
[Polar](https://lightningpolar.com)).

## Architecture

```
bundle.md                          Root bundle (includes foundation + 3 behaviors)
behaviors/
  bitcoin.yaml                     Bitcoin Core L1 tools + wallet-manager agent
  lightning.yaml                   LND Lightning tools + lightning-specialist agent
  aggeus.yaml                      Aggeus market tools + market-maker agent
agents/
  wallet-manager.md                Wallet setup, funding, UTXOs, mining, sending
  lightning-specialist.md          Invoices, payments, channel balance, node info
  market-maker.md                  Browse/create prediction markets on Nostr
context/
  instructions.md                  Root session awareness pointer
  agent-awareness.md               Agent routing table
  aggeus-protocol.md               Aggeus protocol reference (Nostr event kinds)
modules/
  tool-bitcoin-rpc/                7 tools wrapping Bitcoin Core JSON-RPC
  tool-lnd/                        6 tools wrapping LND REST API
  tool-aggeus-markets/             4 tools wrapping Aggeus Nostr relay
```

## Prerequisites

- [Amplifier](https://github.com/microsoft/amplifier) installed
- [Polar](https://lightningpolar.com) (or equivalent local Bitcoin/Lightning stack)
- A running Bitcoin Core node (regtest or signet)
- A running LND node (for Lightning tools)
- A running Nostr relay (for Aggeus tools, optional)

## Setup

1. Clone this repository:

   ```bash
   git clone https://github.com/<your-org>/utxo-bundle.git
   cd utxo-bundle
   ```

2. Copy the environment template and fill in your local paths:

   ```bash
   cp .env.example .env
   ```

   The `.env` file needs paths to your Polar node credentials:

   | Variable | Description |
   |----------|-------------|
   | `BITCOIN_RPC_HOST` / `BITCOIN_RPC_PORT` | Bitcoin Core RPC endpoint |
   | `BITCOIN_COOKIE_FILE` | Path to the `.cookie` file (preferred auth) |
   | `LND_REST_HOST` / `LND_REST_PORT` | LND REST API endpoint |
   | `LND_TLS_CERT` | Path to LND `tls.cert` |
   | `LND_MACAROON_PATH` | Path to LND `admin.macaroon` |
   | `AGGEUS_RELAY_URL` | WebSocket URL of the Nostr relay |
   | `AGGEUS_ORACLE_PRIVKEY` | Oracle private key (only needed to create markets) |
   | `AGGEUS_COORDINATOR_PUBKEY` | Coordinator public key (only needed to create markets) |

3. Run with Amplifier:

   ```bash
   amplifier run --bundle .
   ```

## Agents

### wallet-manager

Bitcoin Core wallet manager for regtest/signet. Handles wallet lifecycle,
address generation, UTXO inspection, splitting, consolidation, mining blocks,
and sending funds.

**Tools:** `manage_wallet`, `mine_blocks`, `generate_address`, `list_utxos`,
`split_utxos`, `consolidate_utxos`, `send_coins`

### lightning-specialist

LND Lightning Network operator. Handles invoice creation, payments, lookups,
channel balance queries, and node info.

**Tools:** `lnd_create_invoice`, `lnd_list_invoices`, `lnd_lookup_invoice`,
`lnd_pay_invoice`, `lnd_get_node_info`, `lnd_channel_balance`

### market-maker

Aggeus prediction market operator for a local Nostr relay. Handles market
browsing, share inspection, and market creation. `aggeus_create_market` is
only available when oracle credentials are configured.

**Tools:** `aggeus_list_markets`, `aggeus_get_market`, `aggeus_list_shares`,
`aggeus_create_market`

## Common Workflows

**Set up a funded wallet:**
```
> Create a new wallet called "alice" and fund it
```
The wallet-manager agent creates the wallet, generates an address, and mines
101 blocks to produce spendable coinbase rewards.

**Create and pay a Lightning invoice:**
```
> Create a 5000 sat invoice on bob's node, then pay it from alice
```
The lightning-specialist agent handles both sides of the payment.

**Browse prediction markets:**
```
> What markets are available?
```
The market-maker agent queries the Nostr relay and presents active markets.

## Module Dependencies

| Module | Dependencies |
|--------|-------------|
| `tool-bitcoin-rpc` | `httpx>=0.27` |
| `tool-lnd` | `httpx` |
| `tool-aggeus-markets` | `websockets>=12.0`, `coincurve>=13.0`, `cryptography>=42.0` |

All modules use [Hatchling](https://hatch.pypa.io/) as the build backend and
register via the `amplifier.modules` entry point group.

## License

MIT
