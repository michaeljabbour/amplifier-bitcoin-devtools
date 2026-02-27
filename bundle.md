---
bundle:
  name: bitcoin-devtools
  version: 0.1.0
  description: >
    Bitcoin Core wallet management, Lightning Network, and Aggeus prediction
    markets for local regtest/signet development via Polar.

includes:
  - bundle: git+https://github.com/microsoft/amplifier-foundation@main
  - bundle: bitcoin-devtools:behaviors/bitcoin
  - bundle: bitcoin-devtools:behaviors/lightning
  - bundle: bitcoin-devtools:behaviors/aggeus
---

# Bitcoin + Lightning + Aggeus Assistant

@bitcoin-devtools:context/instructions.md

@bitcoin-devtools:context/agent-awareness.md

---

@foundation:context/shared/common-system-base.md
