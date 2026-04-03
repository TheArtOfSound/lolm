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

"""Streaming data pipeline for large-scale LOLM training.

Streams from HuggingFace datasets (e.g., FineWeb-Edu) without
downloading the full dataset to disk. Tokenizes on-the-fly
with tiktoken GPT-2 tokenizer.
"""

from __future__ import annotations

import tiktoken
import torch
from torch.utils.data import IterableDataset, DataLoader


class StreamingTokenDataset(IterableDataset):
    """Streaming tokenized dataset from HuggingFace.

    Streams text from a HuggingFace dataset, tokenizes on-the-fly,
    and yields fixed-length token chunks for language modeling.

    Each item returns (x, y) where x = chunk[:-1], y = chunk[1:].

    For DDP: pass rank/world_size to shard the stream so each GPU
    processes different documents with zero overlap.
    """

    def __init__(self, dataset_name: str, seq_len: int,
                 tokenizer_name: str = "gpt2", split: str = "train",
                 dataset_config: str = None,
                 rank: int = 0, world_size: int = 1):
        self.dataset_name = dataset_name
        self.seq_len = seq_len
        self.tokenizer_name = tokenizer_name
        self.split = split
        self.dataset_config = dataset_config
        self.rank = rank
        self.world_size = world_size

    def __iter__(self):
        import glob as _glob
        from datasets import load_dataset

        enc = tiktoken.get_encoding(self.tokenizer_name)

        # Local parquet files: if dataset_name is a glob pattern or existing path
        # e.g.  dataset: "data/fineweb_edu/*.parquet"
        #       dataset: "/home/bry/data/fineweb_edu/*.parquet"
        local_files = _glob.glob(self.dataset_name)
        if local_files:
            ds = load_dataset("parquet",
                              data_files={"train": sorted(local_files)},
                              split="train", streaming=True)
        else:
            # Remote HuggingFace dataset (streaming)
            ds_args = [self.dataset_name]
            if hasattr(self, 'dataset_config') and self.dataset_config:
                ds_args.append(self.dataset_config)
            ds = load_dataset(*ds_args, split=self.split, streaming=True)

        # DDP: true file-level sharding — each rank only downloads its own
        # parquet files, so 16 ranks make 1/16 the connections each.
        # Streaming ds.shard() reads all files and skips examples, which
        # causes 16x simultaneous unauthenticated HF connections → EBADF.
        if self.world_size > 1:
            try:
                # Get file-level shards from the dataset's underlying file list
                n_shards = ds.n_shards if hasattr(ds, 'n_shards') else None
                if n_shards and n_shards >= self.world_size:
                    # Split parquet files: rank k gets files k, k+world_size, k+2*world_size, ...
                    ds = ds.shard(num_shards=self.world_size, index=self.rank, contiguous=False)
                else:
                    # Fewer files than ranks — fall back to example-level round-robin
                    ds = (ex for i, ex in enumerate(ds) if i % self.world_size == self.rank)
            except Exception:
                ds = (ex for i, ex in enumerate(ds) if i % self.world_size == self.rank)

        # Buffer to accumulate tokens across documents
        buffer = []
        chunk_size = self.seq_len + 1  # +1 for target offset

        for example in ds:
            text = example.get("text", "") if isinstance(example, dict) else ""
            if not text:
                continue

            tokens = enc.encode_ordinary(text)
            buffer.extend(tokens)

            # Yield as many full chunks as possible
            while len(buffer) >= chunk_size:
                chunk = buffer[:chunk_size]
                buffer = buffer[chunk_size:]
                chunk_t = torch.tensor(chunk, dtype=torch.long)
                yield chunk_t[:-1], chunk_t[1:]


def get_streaming_dataloader(dataset_name: str, seq_len: int,
                             batch_size: int, tokenizer_name: str = "gpt2",
                             num_workers: int = 2, dataset_config: str = None,
                             rank: int = 0, world_size: int = 1) -> DataLoader:
    """Get a streaming DataLoader for large datasets.

    Args:
        dataset_name: HuggingFace dataset identifier (e.g., "HuggingFaceFW/fineweb-edu")
        seq_len: Sequence length for training
        batch_size: Batch size per GPU
        tokenizer_name: Tokenizer to use (default: gpt2)
        num_workers: Number of data loading workers
        rank: DDP rank (0 for single-GPU)
        world_size: DDP world size (1 for single-GPU)

    Returns:
        DataLoader that streams tokenized chunks
    """
    dataset = StreamingTokenDataset(
        dataset_name=dataset_name,
        seq_len=seq_len,
        tokenizer_name=tokenizer_name,
        dataset_config=dataset_config,
        rank=rank,
        world_size=world_size,
    )
    return DataLoader(
        dataset,
        batch_size=batch_size,
        num_workers=num_workers,
        pin_memory=False,  # pin_memory is CUDA-only; meaningless/harmful on XLA/CPU
        drop_last=True,
    )
