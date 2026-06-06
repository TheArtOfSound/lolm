"""Streaming text utilities for graft training."""

from __future__ import annotations

from typing import Any, Dict, Iterable, Iterator, List, Optional

from datasets import load_dataset


def open_text_stream(
    dataset: str,
    split: str = "train",
    dataset_config: Optional[str] = None,
    seed: int = 42,
    shuffle_buffer: int = 10_000,
):
    kwargs: Dict[str, Any] = {"path": dataset, "split": split, "streaming": True}
    if dataset_config:
        kwargs["name"] = dataset_config
    stream = load_dataset(**kwargs)
    if shuffle_buffer > 0:
        stream = stream.shuffle(seed=seed, buffer_size=shuffle_buffer)
    return stream


def iter_text_batches(
    stream: Iterable[Dict[str, Any]],
    text_field: str = "text",
    batch_size: int = 1,
) -> Iterator[List[str]]:
    batch: List[str] = []
    for example in stream:
        text = str(example.get(text_field, "")).strip()
        if not text:
            continue
        batch.append(text)
        if len(batch) >= batch_size:
            yield batch
            batch = []
    if batch:
        yield batch
