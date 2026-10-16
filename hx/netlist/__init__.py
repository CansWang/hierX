"""Native SPICE-family netlist pipeline (Phase N1): profiles (dialect data tables), lexer (statements with spans),
parser (typed statements), index (scoped, guard-aware declarations across includes and library sections), resolver
(lazy hierarchy with nets, terminals, bindings and references), hashing (token hashes) and the ngspice oracle.
No simulator is needed to extract; simulators are optional oracles (hx/tools.py)."""
