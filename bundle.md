---
bundle:
  name: utxo-bundle
  version: 0.1.0
  description: >
    Bitcoin Core wallet management, Lightning Network, and Aggeus prediction
    markets for local regtest/signet development via Polar.

includes:
  - bundle: git+https://github.com/microsoft/amplifier-foundation@main
  - bundle: utxo-bundle:behaviors/utxo-bundle
---

# Bitcoin + Lightning + Aggeus Assistant

@utxo-bundle:context/instructions.md

@utxo-bundle:context/agent-awareness.md

---

@foundation:context/shared/common-system-base.md
