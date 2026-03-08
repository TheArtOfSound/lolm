# Copyright 2026 Bryan Leonard & Brandyn Leonard
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""Print parameter counts per module for a LOLM config."""

import argparse

from lolm.config import load_config
from lolm.model import LOLM


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", type=str, default="configs/base.yaml")
    args = parser.parse_args()

    cfg = load_config(args.config)
    model = LOLM(cfg.model)
    counts = model.count_parameters()

    print(f"\nLOLM Parameter Counts ({args.config})")
    print("-" * 40)
    for k, v in counts.items():
        if k == "total":
            print("-" * 40)
        print(f"  {k:>12s}: {v:>12,}")
    print()


if __name__ == "__main__":
    main()
