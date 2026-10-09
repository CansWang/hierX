Fixture C project for the libclang frontend. `tests/conftest.py` copies it to a
temp dir and generates `compile_commands.json` with absolute paths.
Shapes covered: cross-file call, static function, macro-wrapped call, function
pointer call, function reference (address taken), declared-only function,
typedef'd struct with nested anonymous union, bitfields, enum return type,
file-scope and function-local static globals.
