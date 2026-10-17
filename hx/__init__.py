"""hx: function-scoped structure extractor.

Given `file:function`, walk the call hierarchy to a chosen depth and record,
for every function reached, its signature, parameters tagged in/out, resolved
types (structs with field offsets), globals touched and call edges. Output is a
schema-versioned JSON graph meant to be viewed in a browser and diffed between
agent sessions.
"""
__version__ = "0.5.0"   # the single source: pyproject reads it (dynamic version)
