"""Engineering core: psychrometrics, bird metabolism, heat/moisture balance,
and the ventilation solver.

This package is pure computation: no file I/O, no GUI dependencies, no
network calls. Every public function must cite its engineering source in
its docstring. If a formula or constant cannot be traced to a reliable
reference (ASHRAE, CIGR, a named breed manual, or a named manufacturer
datasheet), it must not be implemented with invented numbers -- raise
NotImplementedError with a citation-needed note instead.
"""
