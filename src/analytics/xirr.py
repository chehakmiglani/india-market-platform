"""XIRR: the annualised return that makes the NPV of dated cash flows zero.

Convention: money invested is negative, money received (incl. current value) positive.
Uses bisection, which always converges when the flows change sign once (the normal
investor case), unlike Newton which can diverge on SIP-style flows.
"""
from datetime import date


def xnpv(rate: float, flows: list[tuple[date, float]]) -> float:
    t0 = min(d for d, _ in flows)
    return sum(cf / (1 + rate) ** ((d - t0).days / 365.0) for d, cf in flows)


def xirr(flows: list[tuple[date, float]], lo: float = -0.9999, hi: float = 100.0,
         tol: float = 1e-9, max_iter: int = 300) -> float | None:
    flows = [(d, cf) for d, cf in flows if cf]
    if not flows or not (any(cf < 0 for _, cf in flows) and any(cf > 0 for _, cf in flows)):
        return None
    f_lo, f_hi = xnpv(lo, flows), xnpv(hi, flows)
    if f_lo * f_hi > 0:
        return None
    for _ in range(max_iter):
        mid = (lo + hi) / 2
        f_mid = xnpv(mid, flows)
        if abs(f_mid) < tol or (hi - lo) / 2 < tol:
            return mid
        if f_lo * f_mid < 0:
            hi, f_hi = mid, f_mid
        else:
            lo, f_lo = mid, f_mid
    return (lo + hi) / 2
