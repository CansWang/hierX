Fixture for build-variant determinism (review finding H3): `helper()` is an
inline function in a header compiled under `-DUSE_FA` (a.c) and `-DUSE_FB` (b.c).
`tests/test_clang_fe.py::test_index_is_independent_of_cache_state` writes the
compile_commands.json.
