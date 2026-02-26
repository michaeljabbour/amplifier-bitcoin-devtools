# Available Agents

This bundle provides three specialized agents. Delegate to them rather than
attempting domain work directly in the root session.

| Agent | Domain | When to Use |
|-------|--------|-------------|
| `wallet-manager` | Bitcoin Core L1 | Wallet setup, funding, mining, UTXOs, addresses, sending |
| `lightning-specialist` | LND Lightning | Invoices, payments, channel balance, node info |
| `market-maker` | Aggeus markets | Browse markets, view shares, create prediction markets |
