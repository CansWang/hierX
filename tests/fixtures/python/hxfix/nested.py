"""Two outer functions with identically named nested helpers (review finding H2)."""


def outer_a(items):
    def helper(x):
        return x * 2
    return [helper(i) for i in items]


def outer_b(items):
    def helper(x):
        return x + 1
    return [helper(i) for i in items]


def review(items):
    return outer_a(items) + outer_b(items)
