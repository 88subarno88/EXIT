# Calibration report (2026-09-29)

4634 rows, 367 tokens, 7 day(s) (2026-09-22 to 2026-09-29). Target: cost of selling immediately across all measured venues, vs consolidated mid. 5-fold CV grouped by token.
3859 more sales could not be absorbed by the merged book at all (no venue truncated). They can't be fitted, so they're scored instead: 'false comfort' = share a model prices under 10%. Dropped: 799 sales where a venue capped its levels (thin vs truncated unknowable); 2 token-days with no CMC volume/sigma.

| model | Y | delta | median abs err | median factor off | R^2 (log) | false comfort |
|---|---|---|---|---|---|---|
| textbook sqrt, global Y **(shipped)** | 1.65 | 0.500 | 14.5 bps | x1.84 | 0.487 | 81% |
| power law, global Y | 7.05 | 0.719 | 16.4 bps | x1.82 | 0.534 | 46% |
| learned Y per token | per token | 0.719 | 14.8 bps | x1.72 | 0.620 | 46% |

Median absolute error by order size (out-of-fold, bps):

| size | n | sqrt | power | learned |
|---|---|---|---|---|
| $10,000 | 2081 | 9.0 | 8.3 | 7.6 |
| $100,000 | 1829 | 25.3 | 34.6 | 29.6 |
| $1,000,000 | 584 | 25.1 | 40.2 | 37.0 |
| $10,000,000 | 140 | 98.4 | 86.6 | 103.4 |

What predicts a token's Y (GBM feature importance): log_sigma 0.47, history_days 0.19, turnover 0.14, log_mcap 0.12, log_volume 0.08

The learned model did not beat the power law by the required 5%, so it does not ship. The textbook square-root law has the lowest out-of-fold error and ships instead. Published as a negative result.
