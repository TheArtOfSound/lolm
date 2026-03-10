# Copyright 2026 Bryan Leonard & Brandyn Leonard
#
# Licensed under the LOLM Community License Agreement, Version 1.0
# (the "License"); you may not use this file except in compliance
# with the License. You may obtain a copy of the License in the
# LICENSE file at the root of this repository.
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or
# implied. See the License for specific terms and conditions.

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
