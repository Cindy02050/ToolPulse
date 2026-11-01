# src/toolpulse/state/grammar.py
from __future__ import annotations
from sksequitur import Grammar, Parser


class GrammarState:
    """Owns the sksequitur parser; rebuilds from symbols after trim/restore (D15/D6)."""

    def __init__(self) -> None:
        self.symbols: list[str] = []
        self._parser: Parser | None = None

    def _rebuild(self) -> Parser:
        parser = Parser()
        if self.symbols:
            parser.feed(self.symbols)   # full re-feed, mirroring legacy _trim_history (multi_granularity.py:306-308)
        return parser

    def feed(self, symbol: str) -> None:
        self.symbols.append(symbol)
        if self._parser is None:
            self._parser = self._rebuild()
        else:
            self._parser.feed([symbol])

    def current_grammar(self) -> Grammar:
        if self._parser is None:
            self._parser = self._rebuild()
        return Grammar(self._parser.tree)

    def trim(self, n: int) -> None:
        if n <= 0:
            return
        del self.symbols[:n]
        self._parser = None   # lazy rebuild mirrors legacy _trim_history (multi_granularity.py:306-308)

    def snapshot(self) -> list[str]:
        return list(self.symbols)

    def restore(self, symbols: list[str]) -> None:
        self.symbols = list(symbols)
        self._parser = None
