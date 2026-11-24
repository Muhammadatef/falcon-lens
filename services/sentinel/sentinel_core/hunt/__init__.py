"""Hunt mode, deterministic core (docs/design/HUNTER.md section 3). Pure logic, no I/O.

The hunt finds candidates; the existing Investigator cascade and its arbiter decide. Nothing in this package
is a score: ``prescore`` is a queue priority only, and no scoring module may import it.
"""
