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
      cookie_file: /Users/nlandaverde/.polar/networks/2/volumes/bitcoind/backend1/regtest/.cookie

  - module: tool-lnd-bob
    source: ./modules/tool-lnd-bob
    config:
      rest_host: 127.0.0.1
      rest_port: 8085
      tls_cert: /Users/nlandaverde/.polar/networks/2/volumes/lnd/bob/tls.cert
      macaroon_path: /Users/nlandaverde/.polar/networks/2/volumes/lnd/bob/data/chain/bitcoin/regtest/admin.macaroon
---

# Bitcoin UTXO Manager

@utxo-bundle:context/instructions.md

---

@foundation:context/shared/common-system-base.md
