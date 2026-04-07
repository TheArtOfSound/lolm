"""
nfet_trainer.py — NFET-Adaptive Training for LOLM

Applies Noise-Driven Functional Emergence Theory to the training loop:
  1. Rolling Emergent Strength (ES) computed from loss trajectory
  2. Adaptive loss lambdas — shift weight toward lagging components
  3. Gate ridge regularizer — soft penalty for drifting from optimal gate ratio
  4. Regime-aware gate modulation — each regime code biases gate differently

This module WRAPS the existing training loop. It does not modify model.py,
losses.py, or any core architecture code. Toggle on/off via config.

Theory: Bryan Leonard & Brandyn Leonard, Qira LLC
Implementation: Claude Opus 4.6

Usage:
    from lolm.nfet_trainer import NFETTrainingController
    controller = NFETTrainingController(config)

    for step in range(max_steps):
        # ... existing forward/backward ...
        controller.observe(step, losses_dict, gate_mean)
        lambdas = controller.get_adaptive_lambdas()
        ridge_loss = controller.gate_ridge_loss(gate_values)
"""

import math
from collections import deque
from dataclasses import dataclass, field
from typing import Optional

import torch


@dataclass
class NFETTrainingConfig:
    """Configuration for NFET-adaptive training."""
    enabled: bool = True

    # ES computation
    es_window: int = 200          # Rolling window for ES (in steps)
    es_lambda_risk: float = 1.0   # Risk penalty weight in ES = E[O] - λ·σ[O]

    # Adaptive lambdas
    adaptive_lambdas: bool = True
    lambda_adapt_rate: float = 0.02    # How fast lambdas change per step
    lambda_min: float = 0.01           # Floor for any lambda
    lambda_max: float = 2.0            # Ceiling for any lambda

    # Gate ridge regularizer
    gate_ridge_target: float = 0.83    # Known-good gate ratio from 304M
    gate_ridge_strength: float = 0.05  # How strongly to pull toward ridge
    gate_ridge_warmup: int = 5000      # Don't regularize before this step
    gate_ridge_decay: float = 0.9999   # Decay strength as model finds its own equilibrium

    # Phase detection from training dynamics
    collapse_threshold: float = 0.1    # ES below this = training is collapsing
    spike_threshold: float = 0.4       # ES below this = training is unstable


class NFETTrainingController:
    """Monitors training dynamics and adapts hyperparameters using NFET principles.

    The core insight: LOLM's training follows the same phase transition dynamics
    as any coupled network system. The loss lambdas are coupling strengths (κ),
    the gradient noise is σ, and there's an optimal operating ridge where the
    model learns most efficiently.

    This controller estimates where the model is in parameter space and steers
    it toward the ridge.
    """

    def __init__(self, config: NFETTrainingConfig, initial_lambdas: dict):
        self.config = config
        self.initial_lambdas = dict(initial_lambdas)
        self.current_lambdas = dict(initial_lambdas)

        # Rolling history for ES computation
        self._loss_history = deque(maxlen=config.es_window)
        self._token_loss_history = deque(maxlen=config.es_window)
        self._cpc_loss_history = deque(maxlen=config.es_window)
        self._gate_history = deque(maxlen=config.es_window)
        self._regime_entropy_history = deque(maxlen=config.es_window)

        # ES tracking
        self.current_es = 0.5
        self.current_phase = "warmup"
        self.ridge_distance = 0.0

        # Adaptive lambda state
        self._component_health = {
            'token': 1.0,      # How well the decoder is learning
            'cpc': 1.0,        # How well the SSM is learning (via CPC)
            'regime': 1.0,     # How well regime codes are diversifying
            'gate': 1.0,       # How well the gate is arbitrating
        }

        # Gate ridge tracking
        self._ridge_strength = config.gate_ridge_strength

        # Step counter
        self.step = 0

    # ──────────────────────────────────────────────
    # 1. OBSERVE: Record training state each step
    # ──────────────────────────────────────────────

    def observe(self, step: int, losses: dict, gate_mean: float,
                regime_entropy: float = 0.0):
        """Record one training step's metrics.

        Args:
            step: Current training step
            losses: Dict with keys like 'total', 'token', 'cpc_future',
                    'regime', 'competitive', 'changepoint', 'memory', 'manifest'
            gate_mean: Mean gate value across batch (0=latent, 1=surface)
            regime_entropy: Entropy of regime code usage distribution
        """
        self.step = step

        total_loss = losses.get('total', losses.get('loss', 0))
        token_loss = losses.get('token', losses.get('tok', 0))
        cpc_loss = losses.get('cpc_future', losses.get('cpc', 0))

        self._loss_history.append(total_loss)
        self._token_loss_history.append(token_loss)
        self._cpc_loss_history.append(cpc_loss)
        self._gate_history.append(gate_mean)
        self._regime_entropy_history.append(regime_entropy)

        # Update ES and phase
        if len(self._loss_history) >= 20:
            self._compute_es()
            self._classify_phase()
            self._update_component_health()
            self._decay_ridge_strength()

    # ──────────────────────────────────────────────
    # 2. EMERGENT STRENGTH from loss trajectory
    # ──────────────────────────────────────────────

    def _compute_es(self):
        """Compute ES = E[O] - λ·σ[O] where O is normalized loss improvement.

        O(t) = how much loss improved relative to its recent range.
        High O = loss is consistently decreasing (good).
        Low O = loss is flat or oscillating (bad).
        ES penalizes volatility — a model that improves but erratically
        is less healthy than one that improves smoothly.
        """
        losses = list(self._loss_history)
        n = len(losses)
        if n < 20:
            return

        # Compute O(t) for each step: normalized improvement rate
        # O_i = (loss_{i-k} - loss_i) / range, where k is a short lookback
        k = min(10, n // 4)
        o_values = []

        loss_range = max(losses) - min(losses)
        if loss_range < 1e-6:
            # Completely flat — no signal
            self.current_es = 0.5
            return

        for i in range(k, n):
            improvement = losses[i - k] - losses[i]
            o_i = max(0, min(1, 0.5 + improvement / (2 * loss_range)))
            o_values.append(o_i)

        if not o_values:
            return

        mean_o = sum(o_values) / len(o_values)
        std_o = (sum((x - mean_o) ** 2 for x in o_values) / len(o_values)) ** 0.5

        self.current_es = mean_o - self.config.es_lambda_risk * std_o

    def _classify_phase(self):
        """Classify current training phase from ES."""
        if self.step < self.config.gate_ridge_warmup:
            self.current_phase = "warmup"
        elif self.current_es >= 0.5:
            self.current_phase = "ridge"  # Stable, efficient learning
        elif self.current_es >= self.config.spike_threshold:
            self.current_phase = "spike"  # Learning but unstable
        elif self.current_es >= self.config.collapse_threshold:
            self.current_phase = "caution"  # At risk
        else:
            self.current_phase = "collapse"  # Training failing

        # Ridge distance = how far gate is from known-good ratio
        if self._gate_history:
            current_gate = self._gate_history[-1]
            self.ridge_distance = abs(current_gate - self.config.gate_ridge_target)

    # ──────────────────────────────────────────────
    # 3. COMPONENT HEALTH — which subsystem is lagging?
    # ──────────────────────────────────────────────

    def _update_component_health(self):
        """Track health of each component based on its loss trajectory.

        Health = 1.0 means the component is improving normally.
        Health < 0.5 means it's stalling or degrading.

        The adaptive lambdas will increase weight on unhealthy components
        to push them harder.
        """
        def _trend(history, window=50):
            """Compute normalized improvement trend over recent window."""
            vals = list(history)[-window:]
            if len(vals) < 10:
                return 0.5  # Not enough data
            mid = len(vals) // 2
            first_half = sum(vals[:mid]) / mid
            second_half = sum(vals[mid:]) / (len(vals) - mid)
            if first_half == 0:
                return 0.5
            improvement = (first_half - second_half) / abs(first_half)
            # Map to 0-1: positive improvement = healthy
            return max(0, min(1, 0.5 + improvement * 5))

        self._component_health['token'] = _trend(self._token_loss_history)
        self._component_health['cpc'] = _trend(self._cpc_loss_history)

        # Gate health: is it moving toward ridge or away?
        if len(self._gate_history) >= 50:
            gates = list(self._gate_history)
            recent_dist = abs(gates[-1] - self.config.gate_ridge_target)
            older_dist = abs(gates[-50] - self.config.gate_ridge_target)
            improving = older_dist - recent_dist
            self._component_health['gate'] = max(0, min(1, 0.5 + improving * 10))

        # Regime health: is entropy staying high (codes not collapsing)?
        if self._regime_entropy_history:
            recent_entropy = list(self._regime_entropy_history)[-1]
            # For 32 codes, max entropy = log(32) ≈ 3.47
            # For 64 codes, max entropy = log(64) ≈ 4.16
            # Healthy = entropy > 50% of maximum
            max_entropy = 3.5  # Approximate
            self._component_health['regime'] = min(1, recent_entropy / (0.5 * max_entropy))

    # ──────────────────────────────────────────────
    # 4. ADAPTIVE LAMBDAS — shift weight to lagging components
    # ──────────────────────────────────────────────

    def get_adaptive_lambdas(self) -> dict:
        """Return adapted loss lambdas based on component health.

        The NFET principle: coupling strengths (lambdas) should adapt to
        maintain the system on the stability ridge. If a component is
        stalling, increase its coupling. If it's dominating, reduce it.

        Returns:
            Dict of lambda name -> adapted value
        """
        if not self.config.adaptive_lambdas or self.step < self.config.gate_ridge_warmup:
            return self.current_lambdas

        alpha = self.config.lambda_adapt_rate

        # Map component health to lambda adjustments
        # Unhealthy component (health < 0.5) → increase lambda
        # Healthy component (health > 0.5) → gently decrease lambda
        adjustments = {}

        # CPC lambda — most important for SSM learning
        cpc_health = self._component_health['cpc']
        if cpc_health < 0.3:
            # CPC is stuck — SSM isn't learning. Boost aggressively.
            adjustments['lambda_future'] = 1.0 + alpha * 3
        elif cpc_health < 0.5:
            adjustments['lambda_future'] = 1.0 + alpha
        else:
            adjustments['lambda_future'] = 1.0 - alpha * 0.5

        # Competitive gate loss — helps gate learn to choose
        gate_health = self._component_health['gate']
        if gate_health < 0.4:
            adjustments['lambda_competitive'] = 1.0 + alpha * 2
        else:
            adjustments['lambda_competitive'] = 1.0

        # Regime diversity — prevent code collapse
        regime_health = self._component_health['regime']
        if regime_health < 0.5:
            adjustments['lambda_regime'] = 1.0 + alpha * 2
        else:
            adjustments['lambda_regime'] = 1.0

        # Apply adjustments with clamping
        for key, multiplier in adjustments.items():
            if key in self.current_lambdas:
                new_val = self.current_lambdas[key] * multiplier
                new_val = max(self.config.lambda_min,
                             min(self.config.lambda_max, new_val))
                self.current_lambdas[key] = new_val

        return self.current_lambdas

    # ──────────────────────────────────────────────
    # 5. GATE RIDGE REGULARIZER
    # ──────────────────────────────────────────────

    def gate_ridge_loss(self, gate_values: torch.Tensor) -> torch.Tensor:
        """Compute soft regularization loss pulling gate toward ridge ratio.

        This doesn't force the gate to a specific value — it adds a gentle
        quadratic penalty for being far from the known-good operating point.
        The penalty decays over training so the model can find its own
        equilibrium at scale.

        Args:
            gate_values: Tensor of gate outputs [batch, seq_len, d_model]

        Returns:
            Scalar loss to add to total loss
        """
        if self.step < self.config.gate_ridge_warmup:
            return torch.tensor(0.0, device=gate_values.device)

        # Mean gate across batch and sequence
        gate_mean = gate_values.mean()

        # Quadratic penalty centered on ridge target
        ridge_loss = self._ridge_strength * (gate_mean - self.config.gate_ridge_target) ** 2

        return ridge_loss

    def _decay_ridge_strength(self):
        """Decay ridge regularization over training.

        The model should eventually find its own optimal gate ratio.
        We just help it get there faster, then let go.
        """
        self._ridge_strength *= self.config.gate_ridge_decay

    # ──────────────────────────────────────────────
    # 6. DIAGNOSTICS
    # ──────────────────────────────────────────────

    def get_diagnostics(self) -> dict:
        """Return current NFET training state for logging."""
        return {
            'nfet/es': round(self.current_es, 4),
            'nfet/phase': self.current_phase,
            'nfet/ridge_distance': round(self.ridge_distance, 4),
            'nfet/ridge_strength': round(self._ridge_strength, 6),
            'nfet/health_token': round(self._component_health['token'], 3),
            'nfet/health_cpc': round(self._component_health['cpc'], 3),
            'nfet/health_gate': round(self._component_health['gate'], 3),
            'nfet/health_regime': round(self._component_health['regime'], 3),
            'nfet/lambda_future': round(self.current_lambdas.get('lambda_future', 0), 4),
            'nfet/lambda_competitive': round(self.current_lambdas.get('lambda_competitive', 0), 4),
            'nfet/lambda_regime': round(self.current_lambdas.get('lambda_regime', 0), 4),
        }

    def should_alert(self) -> Optional[str]:
        """Return alert message if training is in trouble, else None."""
        if self.current_phase == "collapse":
            return (
                f"NFET ALERT: Training in COLLAPSE phase (ES={self.current_es:.3f}). "
                f"Loss is not improving and may be diverging. "
                f"Consider reducing LR or increasing CPC lambda."
            )
        if self.current_phase == "caution" and self.ridge_distance > 0.15:
            return (
                f"NFET WARNING: Gate drifting from ridge (distance={self.ridge_distance:.3f}, "
                f"gate={list(self._gate_history)[-1]:.3f} vs target {self.config.gate_ridge_target}). "
                f"SSM may not be contributing. Check CPC loss trend."
            )
        return None
