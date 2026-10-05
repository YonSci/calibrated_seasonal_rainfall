"""Alias of plot_smooth_forecasts (the copies were identical apart from imports).

Kept so existing imports and documented commands keep working; edit plot_smooth_forecasts.py instead.
"""
import sys
import plot_smooth_forecasts as _impl

if __name__ == '__main__':
    _impl.main()
else:
    sys.modules[__name__] = _impl
