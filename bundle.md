---
bundle:
  name: utxo-bundle
  version: 0.1.0
  description: Bitcoin UTXO manager — inspect, split, and manage wallets via Bitcoin Core RPC

includes:
  - bundle: git+https://github.com/microsoft/amplifier-foundation@main

tools:
  - module: tool-bitcoin-rpc
    source: ./modules/tool-bitcoin-rpc
    config:
      rpc_host: 127.0.0.1
      rpc_port: 18445
      # cookie_file / rpc_user / rpc_password → BITCOIN_COOKIE_FILE or BITCOIN_RPC_USER / BITCOIN_RPC_PASSWORD

  - module: tool-lnd
    source: ./modules/tool-lnd
    config:
      rest_host: 127.0.0.1
      rest_port: 8085
      # tls_cert / macaroon_path → LND_TLS_CERT / LND_MACAROON_PATH

  - module: tool-aggeus-markets
    source: ./modules/tool-aggeus-markets
    config:
      relay_host: localhost
      relay_port: 8080
      coordinator_pubkey: b49e3064184e3890e230b3bbe7c344cfe8557d5dc46685acf3113c8aa659bb00
      # oracle_private_key → AGGEUS_ORACLE_PRIVKEY
---

# Bitcoin UTXO Manager

@utxo-bundle:context/instructions.md

---

@foundation:context/shared/common-system-base.md
