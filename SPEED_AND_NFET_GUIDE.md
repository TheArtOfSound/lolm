# LOLM Speed Fixes + NFET Integration Guide

## CRITICAL BUG FOUND

**`detach_gradients: true` in the live 1b_lolm_pod.yaml is killing the SSM.**

With this flag, the SSM receives ZERO gradient from the token loss (L_tok).
It can only learn from CPC loss (L_CPC). But CPC is at 5.54 — barely above
random chance (5.55). So the SSM is effectively frozen.

This is why:
- Gate is stuck at 0.90 (surface dominates because SSM never improves)
- Token loss is 7.3+ (decoder has to do everything alone)
- The "seasoning effect" from 304M doesn't appear at this scale

**Fix: Set `detach_gradients: false`.** The SSM will start receiving token
loss gradients and will actually learn to contribute.

---

## SPEED FIXES (Expected: 0.5 → 1.0-1.5 steps/s)

### 1. Disable Memory (FREE speed)
Memory contributes 0% to perplexity but costs compute every forward pass:
- 3 banks × read attention + write attention × 4 chunks = significant overhead
- Set `memory.enabled: false`

### 2. Increase Batch Size Per Chip
Current: batch_size=2 per chip × 16 chips = 32 effective
Proposed: batch_size=4 per chip × 16 chips × 4 accum = 256 effective

TPU chips are underutilized at batch 2. Larger batches amortize the XLA
compilation overhead and reduce the percentage of time spent on mark_step().

### 3. Reduce Save Frequency
Current: save_interval=500 (writes ~2GB checkpoint every 500 steps)
Proposed: save_interval=5000

On TPU, checkpoint saving is synchronous and expensive. At 0.5 steps/s,
you're saving every 16 minutes. That's ~3-5% of training time on I/O alone.

### 4. Reduce Log Frequency
Current: log_interval=10
Proposed: log_interval=50

Each log operation triggers XLA graph materialization. Less frequent logging
means longer uninterrupted XLA execution.

---

## NFET ADAPTIVE TRAINING

### How to Integrate

In your training loop (train_tpu.py or train_tpu_pod.py), add:

```python
from lolm.nfet_trainer import NFETTrainingController, NFETTrainingConfig

# Initialize after model creation
nfet_config = NFETTrainingConfig(
    enabled=True,
    gate_ridge_target=0.83,
    gate_ridge_warmup=5000,
)
initial_lambdas = {
    'lambda_future': loss_cfg.lambda_future,
    'lambda_competitive': loss_cfg.lambda_competitive,
    'lambda_regime': loss_cfg.lambda_regime,
}
nfet_controller = NFETTrainingController(nfet_config, initial_lambdas)

# Inside the training loop, after computing losses:
nfet_controller.observe(
    step=global_step,
    losses={
        'total': total_loss.item(),
        'token': tok_loss.item(),
        'cpc_future': cpc_loss.item(),
    },
    gate_mean=gate_mean.item(),
    regime_entropy=regime_entropy,  # if available
)

# Get adapted lambdas (replaces fixed lambdas)
adapted = nfet_controller.get_adaptive_lambdas()
# Use adapted['lambda_future'] etc. in loss computation

# Add ridge regularizer to total loss
ridge_loss = nfet_controller.gate_ridge_loss(gate_values)
total_loss = total_loss + ridge_loss

# Log NFET diagnostics
if step % log_interval == 0:
    diags = nfet_controller.get_diagnostics()
    # Add to your logging: diags has nfet/es, nfet/phase, etc.

# Check for alerts
alert = nfet_controller.should_alert()
if alert:
    print(alert)
```

### What the NFET Controller Does

1. **Computes ES** from loss trajectory — measures training stability
2. **Classifies phase** — ridge (good), spike (unstable), collapse (failing)
3. **Adapts lambdas** — if CPC is stuck, it boosts lambda_future to push SSM harder
4. **Gate ridge loss** — gently pulls gate toward 0.83 target, decaying over time
5. **Alerts** — warns when training enters collapse or gate drifts too far

### When NOT to Use It

- During the first 5000 steps (warmup period)
- If you want a clean baseline comparison (set enabled: false)
- If training is already converging well (don't fix what isn't broken)

---

## RECOMMENDED NEXT RUN

```bash
# Use the fast config with SSM gradients enabled
python train_tpu_pod.py --config configs/scale/1b_lolm_pod_fast.yaml
```

This config:
- Fixes the SSM gradient detach bug
- Disables dead-weight memory
- Doubles batch size for better chip utilization
- Adds gradient accumulation for effective batch 256
- Reduces I/O overhead from saves and logs
- Increases CPC lambda to push SSM learning harder

Expected result: SSM starts learning → gate naturally moves toward 83/17 →
token loss drops faster → the "seasoning effect" appears at scale.
