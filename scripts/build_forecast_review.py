"""Alias of delivery_render (the copies were identical apart from imports).

Kept so existing imports and documented commands keep working; edit delivery_render.py instead.
"""
import sys
import delivery_render as _impl

if __name__ == '__main__':
    _impl.main()
else:
    sys.modules[__name__] = _impl
