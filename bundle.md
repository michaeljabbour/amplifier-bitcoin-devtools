---
bundle:
  name: utxo-bundle
  version: 0.1.0
  description: Bitcoin UTXO manager — inspect and plan splits for a Bitcoin Core wallet

includes:
  - bundle: git+https://github.com/microsoft/amplifier-foundation@main

tools:
  - module: tool-bitcoin-rpc
    source: ./modules/tool-bitcoin-rpc
    config:
      rpc_host: 127.0.0.1
      rpc_port: 18445
      cookie_file: /Users/nlandaverde/.polar/networks/2/volumes/bitcoind/backend1/regtest/.cookie
---

# Bitcoin UTXO Manager

@utxo-bundle:context/instructions.md

---

@foundation:context/shared/common-system-base.md
