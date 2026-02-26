# Aggeus Protocol Reference

## Overview

Aggeus is a Bitcoin-native prediction market protocol. It lets participants bet on real-world outcomes using Bitcoin as collateral, and Lightning Network for instant settlement, and Nostr as the communication layer.

The core insight is that a market maker can lock satoshis into a smart contract, publish their position publicly, and go offline — a buyer can later take the opposite side without any coordination with the maker. The **coordinator** acts as a non-custodial proxy that wires the two positions together. The **oracle** holds the secret that unlocks one side when the market resolves.

No trusted third party ever holds user funds. Settlement is enforced by Bitcoin script.

---

## Protocol Participants

### Oracle

The oracle creates markets and controls resolution. At market creation the oracle generates two random secrets — the **yes preimage** and the **no preimage** — and publishes only their SHA256 hashes in the market definition event. At resolution, the oracle reveals exactly one preimage (whichever outcome occurred). That revealed value is the key that unlocks the winning side's contract on-chain.

The oracle must keep both preimages secret until resolution. If they are lost, the market cannot be settled.

### Coordinator

The coordinator is a non-custodial proxy between makers and buyers. It never holds funds directly — all sats sit in Bitcoin smart contracts that require the coordinator's signature alongside the user's. The coordinator:

- Accepts liquidity offers from makers and broadcasts their funding transactions
- Matches buyers with open shares and issues Lightning invoices for the purchase cost
- Broadcasts the **midstate transaction** once a buyer pays, which pays the maker immediately and moves the share into a new contract for the buyer

The coordinator earns fees and has a financial incentive to act honestly, but cannot steal funds because the contracts require user co-signatures.

### Maker

The maker is a liquidity provider who opens positions. They pick a prediction (YES or NO), express a **confidence percentage**, lock 10,000 sats per share into a 2-of-2 contract with the coordinator, and publish the share to Nostr. Once the share is funded, the maker can go offline. If a buyer takes the position, the maker is paid immediately via the midstate transaction.

Higher confidence means the maker receives less upfront but is more exposed to loss if wrong.

### Buyer

The buyer takes the counter-position to an open share. They pay a cost determined by the maker's confidence, receive a Lightning preimage that secures their claim, and if they win at resolution they can sweep the full 10,000 sat deposit from their mirror contract.

---

## Market Lifecycle

### 1. Creation

The oracle generates a market with a question, a resolution block height, and the two preimage hashes. This is published as a **kind 46416** Nostr event signed by the oracle's key. The event is immutable — the hashes cannot change after publication.

The oracle must save the two preimages offline. They are not recoverable.

### 2. Share Publishing

A maker constructs a funding transaction that deposits 10,000 sats (per share) into a Taproot address jointly controlled by themselves and the coordinator. They send the unsigned transaction and pre-signed contract data to the coordinator via an encrypted Nostr DM.

The coordinator validates everything, charges a small fee via Lightning, then broadcasts the funding transaction and publishes the share as a **kind 46415** Nostr event. The share is now publicly visible and open for buyers.

### 3. Trading

A buyer sees an open share and sends a buy request to the coordinator via encrypted DM. The coordinator responds with a Lightning invoice for the buyer cost. Once the buyer pays:

1. The coordinator broadcasts the **midstate transaction**, which spends the maker's funded share and pays the maker their upfront amount immediately.
2. The coordinator creates a **mirror contract** — a new on-chain output funded by the coordinator — that the buyer can claim if they win.
3. The share state is updated to `proxied` on Nostr.

The buyer now holds a position. The maker has been paid out and has no further role.

### 4. Resolution

At the resolution block height, the oracle publishes the preimage for the outcome that occurred. Anyone can verify it matches the hash in the market definition.

- The winning side uses the revealed preimage to satisfy the hash-lock in their contract and sweep the 10,000 sats.
- The losing side's contract output is claimable by the counterparty.

Settlement is fully on-chain and requires no further oracle action beyond revealing the preimage.

---

## Nostr Event Structure

### Market Definition — kind 46416

Published by the oracle. Immutable after creation.

**Tags:**
- `t` → `"market_definition"`
- `d` → `<market_id>` (used for deduplication)
- `p` → oracle pubkey

**Content:** A JSON array serialized as a string:

```
[version, name, market_id, oracle_pubkey, coordinator_pubkey,
 resolution_blockheight, yes_hash, no_hash, [relay_urls]]
```

At resolution, the oracle publishes a second kind 46416 event tagged `"market_resolution"` containing the winning preimage.

### Share Announcement — kind 46415

Published by the coordinator when a maker's share is funded. Immutable after publication.

**Tags:**
- `e` → `<market_id>` (links this share to its market)
- `t` → `"share"`
- `d` → `<share_id>` (used for deduplication)

**Content:** A JSON object with the share's prediction, confidence percentage, deposit amount, funding outpoint, and a reference back to the market's shareable data.

### Share State Update — kind 36415

A parameterized replaceable event. As the share's status changes (e.g. from `for_sale` to `proxied`), the coordinator publishes updated state events with the same `d` tag, which replace the previous state on compatible relays.

---

## Share Pricing

Every share represents a 10,000 sat position. The buyer's cost is determined by how confident the maker claims to be:

```
buyer_cost = (100 − confidence_percentage) × 100  sats
```

The maker receives that same amount immediately when the buyer purchases (via the midstate transaction). The remaining sats stay locked in the smart contract as the maker's at-risk collateral.

| Maker confidence | Buyer pays | Maker gets upfront | Maker's collateral at risk |
|-----------------|------------|-------------------|---------------------------|
| 90% | 1,000 sats | 1,000 sats | 9,000 sats |
| 70% | 3,000 sats | 3,000 sats | 7,000 sats |
| 50% | 5,000 sats | 5,000 sats | 5,000 sats |
| 30% | 7,000 sats | 7,000 sats | 3,000 sats |

A maker with 70% confidence is essentially saying: "I'll accept 3,000 sats now in exchange for risking 7,000 sats on my prediction being right."

---

## Preimages and Settlement

At market creation the oracle generates two 32-byte random secrets:

- **yes_preimage** — revealed if YES is the correct outcome
- **no_preimage** — revealed if NO is the correct outcome

Their SHA256 hashes are embedded in the market definition and cannot be changed. The smart contracts for both the maker's side and the buyer's mirror contract use these hashes as spending conditions:

- The maker's contract can be spent by the maker if they supply the yes_preimage (if they bet YES), or by the coordinator if the no_preimage is revealed.
- The buyer's mirror contract is the inverse: the buyer can sweep it with the revealed preimage if they bet correctly.

The Lightning payment the buyer makes to acquire a position also carries a preimage. The coordinator uses this to authorize the buyer's on-chain claim. If the oracle never reveals a preimage, neither side can claim — which is why the oracle's duty to publish at resolution is a core protocol assumption.

Preimages must be stored by the oracle outside the system. There is no recovery mechanism.

---

## Relay Communication

All public protocol state — markets and shares — is broadcast over Nostr using WebSocket connections to one or more relays. Private coordination between participants (maker ↔ coordinator, buyer ↔ coordinator) happens via NIP-04 encrypted direct messages (kind 4).

**Typical flow for reading state:**

1. Client opens a WebSocket to the relay and sends a `REQ` message with a filter (e.g. `kinds: [46416]`).
2. The relay streams back matching `EVENT` messages.
3. The relay sends `EOSE` (end of stored events) when caught up.
4. The client continues listening for new events in real time.

**Typical flow for publishing:**

1. Client sends a signed `EVENT` message to the relay.
2. The relay responds with `OK` to acknowledge receipt.

**Key filters used:**

| Purpose | Kind | Filter tags |
|---------|------|-------------|
| List all markets | 46416 | `#t: market_definition` |
| Get a specific market | 46416 | `#d: <market_id>` |
| List shares for a market | 46415 | `#e: <market_id>`, `#t: share` |
| Get share state updates | 36415 | `#t: share_state`, authors: coordinators |
| Market resolution | 46416 | `#d: <market_id>`, `#t: market_resolution` |
| Coordinator DMs | 4 | `#p: <recipient_pubkey>` |
