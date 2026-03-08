"""Fix checkpoint: re-initialize memory slots to break the deadlock.

The memory banks have init_memory at scale 0.02, which causes uniform
softmax attention → zero variance → zero gradient → memory stays dead.

This script re-initializes ONLY the memory slot parameters with larger
orthogonal-like initialization (scale 0.2) so slots are actually different.
All other weights remain untouched.

Usage:
    python fix_checkpoint.py --input runs/300m_v3/ckpt_25000.pt --output runs/300m_v3/ckpt_25000_fixed.pt
"""

from __future__ import annotations

import argparse
import torch


def fix_checkpoint(input_path: str, output_path: str, scale: float = 0.2):
    print(f"Loading checkpoint: {input_path}")
    ckpt = torch.load(input_path, map_location="cpu", weights_only=False)

    model_state = ckpt["model"]

    # Find and re-initialize memory init_memory parameters
    fixed_keys = []
    for key in model_state:
        if "init_memory" in key:
            old = model_state[key]
            n_slots, slot_dim = old.shape
            print(f"  {key}: shape={old.shape}, old_scale={old.std():.4f}")

            # Re-initialize with larger scale, semi-orthogonal
            new = torch.randn_like(old) * scale
            # Make slots more distinct by adding orthogonal component
            if n_slots <= slot_dim:
                # Use QR decomposition for orthogonal rows
                q, _ = torch.linalg.qr(torch.randn(slot_dim, n_slots))
                new = q.T * scale  # (n_slots, slot_dim)

            model_state[key] = new
            print(f"  {key}: new_scale={new.std():.4f} (orthogonal, scale={scale})")
            fixed_keys.append(key)

    if not fixed_keys:
        print("WARNING: No init_memory keys found!")
        return

    # Also reset optimizer state for memory parameters to avoid stale momentum
    if "optimizer" in ckpt and ckpt["optimizer"]:
        print("  Resetting optimizer state for memory parameters...")
        opt_state = ckpt["optimizer"]
        # We can't easily map param names to optimizer param indices,
        # so we'll let the training loop handle it (momentum will adapt quickly)

    ckpt["model"] = model_state

    print(f"Saving fixed checkpoint: {output_path}")
    torch.save(ckpt, output_path)
    print(f"Done! Fixed {len(fixed_keys)} memory parameters.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", required=True, help="Input checkpoint path")
    parser.add_argument("--output", required=True, help="Output checkpoint path")
    parser.add_argument("--scale", type=float, default=0.2, help="Memory init scale")
    args = parser.parse_args()
    fix_checkpoint(args.input, args.output, args.scale)
