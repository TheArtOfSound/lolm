# Copyright 2026 Bryan Leonard & Brandyn Leonard
# SPDX-License-Identifier: AGPL-3.0-or-later

"""One-time data tokenization script."""

import argparse

from lolm.config import load_config
from lolm.data import tokenize_and_cache


def main():
    parser = argparse.ArgumentParser(description="Tokenize and cache dataset")
    parser.add_argument("--config", type=str, default="configs/base.yaml")
    parser.add_argument("--split", type=str, default="train")
    args = parser.parse_args()

    cfg = load_config(args.config)
    path = tokenize_and_cache(cfg.data.dataset, cfg.data.cache_dir, args.split)
    print(f"Done: {path}")


if __name__ == "__main__":
    main()
