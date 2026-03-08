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

"""Data loading and tokenization for LOLM training.

Uses TinyStories dataset with tiktoken GPT-2 tokenizer.
Tokenized data is cached as memory-mapped numpy arrays.
"""

import os
from pathlib import Path

import numpy as np
import tiktoken
import torch
from torch.utils.data import Dataset, DataLoader


class TokenizedDataset(Dataset):
    """Memory-mapped tokenized text dataset.

    Each item returns a (seq_len+1,) chunk: input = [:-1], target = [1:].
    """

    def __init__(self, data_path: str, seq_len: int):
        self.seq_len = seq_len
        self.data = np.memmap(data_path, dtype=np.uint16, mode="r")
        self.n_chunks = (len(self.data) - 1) // seq_len

    def __len__(self):
        return self.n_chunks

    def __getitem__(self, idx):
        start = idx * self.seq_len
        chunk = self.data[start:start + self.seq_len + 1].astype(np.int64)
        x = torch.from_numpy(chunk[:-1])
        y = torch.from_numpy(chunk[1:])
        return x, y


def tokenize_and_cache(dataset_name: str, cache_dir: str,
                       split: str = "train") -> str:
    """Download, tokenize, and cache a HuggingFace dataset.

    Returns path to the cached .bin file.
    """
    cache_path = Path(cache_dir)
    cache_path.mkdir(parents=True, exist_ok=True)
    bin_path = cache_path / f"{split}.bin"

    if bin_path.exists():
        print(f"Using cached tokenized data: {bin_path}")
        return str(bin_path)

    print(f"Tokenizing {dataset_name} ({split})...")
    from datasets import load_dataset
    ds = load_dataset(dataset_name, split=split, trust_remote_code=True)

    enc = tiktoken.get_encoding("gpt2")
    all_tokens = []
    for i, example in enumerate(ds):
        text = example.get("text", "")
        if text:
            tokens = enc.encode_ordinary(text)
            all_tokens.extend(tokens)
        if (i + 1) % 100000 == 0:
            print(f"  Tokenized {i+1} examples ({len(all_tokens):,} tokens)")

    print(f"Total tokens: {len(all_tokens):,}")

    # Save as uint16 (GPT-2 vocab fits in uint16)
    arr = np.array(all_tokens, dtype=np.uint16)
    arr.tofile(str(bin_path))
    print(f"Saved to {bin_path} ({bin_path.stat().st_size / 1e6:.1f} MB)")

    return str(bin_path)


def get_dataloader(dataset_name: str, cache_dir: str, seq_len: int,
                   batch_size: int, split: str = "train") -> DataLoader:
    """Get a DataLoader for tokenized data."""
    bin_path = tokenize_and_cache(dataset_name, cache_dir, split)
    dataset = TokenizedDataset(bin_path, seq_len)
    return DataLoader(
        dataset,
        batch_size=batch_size,
        shuffle=(split == "train"),
        num_workers=0,
        pin_memory=False,
        drop_last=True,
    )
