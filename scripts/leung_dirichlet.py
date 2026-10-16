"""Leung–Dirichlet calibration (process_calib.py by A. G. Munoz and T. Demissie, ILRI / Alisios Corporation; docs/51),
as methods: a modified-Leung member-wise affine bias correction and an identity-anchored Dirichlet recalibration.

The uploaded pipeline, stage by stage:
  1. SEAS5 seasonal totals put on the CHIRPS grid (nearest neighbour; here the project's 4 x 4 block copy of the 1 deg cells).
  2. Bias correction: modified-Leung member-wise affine calibration in total space -> bias_methods.py 'leung_affine'
     (each member's own climatology, spread ratio from a beta-pooled model spread, limits 0.5-2).
  3. Tercile probabilities: the fraction of corrected members below the lower / above the upper CHIRPS tercile (no
     smoothing, no climatology blend) -> member_probabilities().
  4. Probability calibration: Identity-Anchored Dirichlet (IAD) recalibration p' = softmax(A log p + b), fitted once
     on the training years' probabilities and observed categories, pooled over cells -> IADDirichlet (unchanged).
  5. (SPBI, a pasture index from NDVI and the calibrated seasonal mean: not part of rainfall calibration; not implemented.)
"""
import numpy as np

EPS = 1e-12

# Display names (site, figures, maps, method selection and summary); the keys are the benchmark's.
NAME = 'Leung–Dirichlet calibration'
CREDIT = 'from process_calib.py by Á. G. Muñoz and T. Demissie (ILRI)'
SHORT = dict(ld_full='Leung–Dirichlet (as uploaded)', ld_no_dirichlet='Leung + member counts', iad_on_mvs='MVS + Dirichlet',
             leung_blend='Leung + published blend', leung_affine='Leung affine (amounts)')
LONG = dict(ld_full='Leung–Dirichlet calibration as uploaded: modified-Leung affine → member counts → identity-anchored Dirichlet',
            ld_no_dirichlet='Modified-Leung affine → member counts (the uploaded script with --no_dirichlet)',
            iad_on_mvs='Published MVS → member counts → identity-anchored Dirichlet (the Dirichlet alone)',
            leung_blend='Modified-Leung affine → the published smoothed counts and climatology blend (the Leung correction alone)',
            leung_affine='Modified-Leung affine ensemble (amounts)')


def _softmax(z, axis=-1):
    z = z - np.max(z, axis=axis, keepdims=True)
    e = np.exp(z)
    return e / np.sum(e, axis=axis, keepdims=True)


class IADDirichlet:
    """Identity-Anchored Dirichlet (IAD) recalibrator, as in process_calib.py (DirichletCalibrator):
      p' = softmax(A log(p) + b);
      penalties 0.5 lambda_off sum_{i != j} A_ij^2 + 0.5 lambda_diag sum_i (A_ii - 1)^2 + 0.5 lambda_b ||b||^2;
      fitted by mean negative log-likelihood with L-BFGS-B from the identity (A = I, b = 0); probabilities clipped at 1e-12.
    Defaults are those of the script without flags (--dirichlet_reg 1e-2: off 1e-2, diag and bias 0.1 x off).
    Author of the method: Angel G. Munoz (a regularized variant of Dirichlet calibration, Kull et al. 2019).
    """

    def __init__(self, reg=None, reg_off=None, reg_diag=None, reg_b=None, maxiter=400, tol=1e-6):
        if reg_off is None and reg is not None:
            reg_off = float(reg)
        if reg_diag is None:
            reg_diag = 0.1 * (reg_off if reg_off is not None else 1e-2)
        if reg_b is None:
            reg_b = 0.1 * (reg_off if reg_off is not None else 1e-2)
        self.reg_off = float(reg_off if reg_off is not None else 1e-2)
        self.reg_diag, self.reg_b = float(reg_diag), float(reg_b)
        self.maxiter, self.tol = maxiter, tol
        self.A = self.b = None
        self.converged = None

    def fit(self, P, y, w=None):
        """w: optional sample weights (the original weighs every sample equally; None reproduces it)."""
        from scipy.optimize import minimize
        P = np.clip(P, EPS, 1.0)
        P = P / P.sum(axis=1, keepdims=True)
        y = np.asarray(y, int)
        N, K = P.shape
        logP = np.log(P)
        w = np.full(N, 1.0 / N) if w is None else np.asarray(w, float) / np.sum(w)
        x0 = np.concatenate([np.eye(K).ravel(), np.zeros(K)])
        unpack = lambda x: (x[:K * K].reshape(K, K), x[K * K:])
        I = np.eye(K)

        def loss_grad(x):
            A, b = unpack(x)
            Pcal = _softmax(logP @ A.T + b, axis=1)
            nll = -(w @ np.log(np.clip(Pcal[np.arange(N), y], EPS, 1.0)))
            A_off, diag_diff = A * (1.0 - I), np.diag(A) - 1.0
            reg = 0.5 * self.reg_off * np.sum(A_off * A_off) + 0.5 * self.reg_diag * np.sum(diag_diff ** 2) + 0.5 * self.reg_b * np.sum(b * b)
            Y = np.zeros_like(Pcal)
            Y[np.arange(N), y] = 1.0
            G = (Pcal - Y) * w[:, None]
            dA = G.T @ logP + self.reg_off * A_off + self.reg_diag * np.diag(diag_diff)
            db = G.sum(axis=0) + self.reg_b * b
            return nll + reg, np.concatenate([dA.ravel(), db])
        res = minimize(loss_grad, x0, jac=True, method='L-BFGS-B', options=dict(maxiter=self.maxiter, ftol=self.tol))
        self.A, self.b = unpack(res.x)
        self.converged = bool(res.success)
        return self

    def predict(self, P):
        P = np.clip(P, EPS, 1.0)
        P = P / P.sum(axis=1, keepdims=True)
        return _softmax(np.log(P) @ self.A.T + self.b, axis=1)

    def params(self):
        return dict(A=np.asarray(self.A).round(4).tolist(), b=np.asarray(self.b).round(4).tolist(), converged=self.converged,
                    reg_off=self.reg_off, reg_diag=self.reg_diag, reg_b=self.reg_b)


def member_probabilities(members, q1, q2):
    """Fraction of members below q1, between (inclusive) and above q2, per cell (process_calib.py; no smoothing).
    members: (member, cell) corrected totals; NaN cells give NaN probabilities."""
    m = np.asarray(members, float)
    ok = np.isfinite(m).all(0) & np.isfinite(q1) & np.isfinite(q2)
    lo = (m < q1[None, :]).mean(0)
    up = (m > q2[None, :]).mean(0)
    p = np.stack([lo, 1.0 - lo - up, up], -1)
    p[~ok] = np.nan
    return p


def observed_category(obs, q1, q2):
    """0 below (< q1), 1 near (q1..q2 inclusive), 2 above (> q2); -1 where undecidable (process_calib.py)."""
    y = np.full(obs.shape, -1, int)
    ok = np.isfinite(obs) & np.isfinite(q1) & np.isfinite(q2)
    y[ok & (obs < q1)] = 0
    y[ok & (obs >= q1) & (obs <= q2)] = 1
    y[ok & (obs > q2)] = 2
    return y
