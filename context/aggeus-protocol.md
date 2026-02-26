# Aggeus Protocol Reference

<!-- 
  Fill in each section below with the protocol details the market-maker
  agent needs to operate correctly. This file is @-mentioned by the
  market-maker agent so its contents load into that agent's context only.
-->

## Overview

<!-- 
  High-level description of what Aggeus is:
  - What problem does it solve?
  - How does it relate to Bitcoin / Lightning / Nostr?
  - Who are the participants (oracle, coordinator, maker, buyer)?
-->

## Protocol Participants

<!-- 
  Define each role and what they do:

  ### Oracle
  - Who signs market creation events?
  - Who holds the yes/no preimages?
  - What happens at resolution?

  ### Coordinator
  - What does the coordinator do?
  - How does the coordinator_pubkey get used?

  ### Maker
  - What does a maker do?
  - How do they publish shares?
  - What does "confidence percentage" mean from the maker's perspective?

  ### Buyer
  - How does a buyer take a position?
  - How is buyer cost calculated?
  - What does the buyer receive if they win?
-->

## Market Lifecycle

<!-- 
  Describe the full lifecycle of a market:

  ### Creation
  - What happens when a market is created?
  - What data is published to the relay?

  ### Share Publishing
  - How do makers publish shares?
  - What determines the price?

  ### Trading
  - How do buyers acquire shares?
  - What role does Lightning play in the trade?

  ### Resolution
  - How does the oracle resolve the market?
  - What happens to the preimages?
  - How do winners get paid?
-->

## Nostr Event Structure

<!-- 
  Document the wire format for each event type:

  ### Market Definition (kind 46416)
  - Tag structure: #t, #d, #p
  - Content: MarketShareableData array layout
    [version, name, market_id, oracle_pubkey, coordinator_pubkey,
     resolution_blockheight, yes_hash, no_hash, relays]

  ### Share Announcement (kind 46415)
  - Tag structure: #e, #t
  - Content: share object fields
    (share_id, prediction, confidence_percentage, deposit,
     funding_outpoint, etc.)
-->

## Share Pricing

<!-- 
  Explain the pricing model:
  - How confidence percentage maps to buyer cost
  - What the deposit amount represents
  - The formula: buyer_cost = (100 - confidence_pct) * 100 sats
  - Worked examples at different confidence levels
-->

## Preimages and Settlement

<!-- 
  Explain the cryptographic settlement mechanism:
  - What are the yes/no preimages?
  - How are the hashes (SHA256 of preimages) used?
  - How does revealing a preimage settle Lightning payments?
  - Why must preimages be stored securely?
-->

## Relay Communication

<!-- 
  Document how the tools talk to the Nostr relay:
  - WebSocket connection to ws://host:port
  - REQ/EVENT/EOSE/OK message flow
  - What filters are used for each query type
-->
