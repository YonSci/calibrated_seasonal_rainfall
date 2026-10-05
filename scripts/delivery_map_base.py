"""Alias of plot_forecast_products (the copies were identical apart from imports).

Kept so existing imports and documented commands keep working; edit plot_forecast_products.py instead.
"""
import sys
import plot_forecast_products as _impl

if __name__ == '__main__':
    _impl.main()
else:
    sys.modules[__name__] = _impl
