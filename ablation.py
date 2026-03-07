# Copyright 2026 Bryan Leonard
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

"""Run all 6 ablation configurations sequentially."""

import argparse
import subprocess
import sys
from pathlib import Path


ABLATION_CONFIGS = [
    "configs/ablations/01_plain_decoder.yaml",
    "configs/ablations/02_decoder_memory.yaml",
    "configs/ablations/03_decoder_ssm.yaml",
    "configs/ablations/04_decoder_ssm_memory.yaml",
    "configs/ablations/05_decoder_ssm_memory_regime.yaml",
    "configs/ablations/06_full.yaml",
]


def main():
    parser = argparse.ArgumentParser(description="Run LOLM ablation study")
    parser.add_argument("--configs", nargs="+", default=ABLATION_CONFIGS,
                        help="Config files to run (default: all 6)")
    args = parser.parse_args()

    for i, config in enumerate(args.configs):
        print(f"\n{'='*60}")
        print(f"ABLATION {i+1}/{len(args.configs)}: {config}")
        print(f"{'='*60}\n")

        if not Path(config).exists():
            print(f"Config not found: {config}, skipping.")
            continue

        result = subprocess.run(
            [sys.executable, "train.py", "--config", config],
            cwd=str(Path(__file__).parent),
        )

        if result.returncode != 0:
            print(f"Training failed for {config} (exit code {result.returncode})")
        else:
            print(f"Completed: {config}")

    print(f"\n{'='*60}")
    print("All ablations complete.")
    print(f"{'='*60}")


if __name__ == "__main__":
    main()
