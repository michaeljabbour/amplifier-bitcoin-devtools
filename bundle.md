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

  - module: tool-lnd
    source: ./modules/tool-lnd
    config:
      rest_host: 127.0.0.1
      rest_port: 8085
      tls_cert: /Users/nlandaverde/.polar/networks/2/volumes/lnd/bob/tls.cert
      macaroon_path: /Users/nlandaverde/.polar/networks/2/volumes/lnd/bob/data/chain/bitcoin/regtest/admin.macaroon

  - module: tool-aggeus-markets
    source: ./modules/tool-aggeus-markets
    config:
      relay_host: localhost
      relay_port: 8080
      oracle_private_key: c26ba1a929b5c86e31d18435d81a6daaf689828b2c4cde3ea24bba3e48ffbcff
      coordinator_pubkey: b49e3064184e3890e230b3bbe7c344cfe8557d5dc46685acf3113c8aa659bb00
      maker_private_key: bd5ea5289be48c372b062873d7e5009ff61a681291e06906970a7be50676927f
---

# Bitcoin UTXO Manager

@utxo-bundle:context/instructions.md

---

@foundation:context/shared/common-system-base.md
