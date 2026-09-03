# DarwinSpot product contract

This project follows the approved `DarwinSpot-Complete-PRD.md` supplied at build time. The authoritative copy remains at `C:\Users\ACER\Downloads\DarwinSpot-Complete-PRD.md` and the equivalent `cek\outputs` path; this file records the implementation boundary so the repository does not silently drift.

## Required product

One owner connects one dedicated Binance Agent OS account, writes a four-part spot mandate (assets, entry, sizing, exit), chooses `READ_ONLY`, `APPROVAL_REQUIRED`, or `AUTO_BOUNDED`, and can run an autonomous typed action. The backend records evidence, immutable intents, budget result, upstream order identifiers, fills, cancellations, and reconciliation state.

## Hard controls

There is one hard trading guard: a rolling 24-hour buy budget. `Spent Amount` is verified buy fills from the prior 24 hours plus quote value committed to open buy orders. `Available Budget` is the configured budget minus that amount, never below zero. Sells and cancellations do not consume the buy budget. The owner emergency stop blocks new submissions and requests cancellation of DarwinSpot orders.

No pair allowlist, per-order cap, order-count cap, cooldown, allocation band, reserve, stop-loss, drawdown, weekly cap, or monthly cap is added.

## Excluded scope

No leverage, margin, futures, options, transfers, withdrawals, bridging, liquidity pools, multi-agent orchestration, social feeds, arbitrary browsing, performance guarantee, or fake/paper production evidence.
