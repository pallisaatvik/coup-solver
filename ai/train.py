"""
Training script for the CFR bot.
Usage: python3 ai/train.py [--iterations N] [--checkpoint N] [--output path]
"""

import argparse
import sys
import time

sys.setrecursionlimit(10_000)


def main() -> None:
    parser = argparse.ArgumentParser(description="Train the Coup CFR bot")
    parser.add_argument("--iterations", type=int, default=500_000)
    parser.add_argument("--checkpoint", type=int, default=50_000)
    parser.add_argument("--output",     default="ai/strategy.pkl")
    args = parser.parse_args()

    from ai.cfr import run_iteration, save, strategy_sum

    print(f"Training for {args.iterations:,} iterations → {args.output}")
    t0 = time.time()

    for i in range(1, args.iterations + 1):
        run_iteration()
        if i % args.checkpoint == 0:
            elapsed = time.time() - t0
            rate    = i / elapsed
            print(f"  [{i:>{len(str(args.iterations))},}/{args.iterations:,}]"
                  f"  {elapsed:6.0f}s  ({rate:.0f} it/s)"
                  f"  {len(strategy_sum):,} info sets  — saving")
            save(args.output)

    save(args.output)
    elapsed = time.time() - t0
    print(f"Done. {args.iterations:,} iterations in {elapsed:.1f}s "
          f"({args.iterations/elapsed:.0f} it/s)  "
          f"{len(strategy_sum):,} info sets total")


if __name__ == "__main__":
    main()
