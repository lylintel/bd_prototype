import re

from rank_bm25 import BM25Plus

from ai.context import is_builtin_description, metadata_card


WORDS = re.compile(r"[a-zA-Z_$][a-zA-Z0-9_$]*|[0-9]+|[\u3400-\u9fff]+")


def tokenize(text):
    tokens = []
    for word in WORDS.findall(text.casefold()):
        tokens.append(word)
        if "_" in word:
            tokens.extend(part for part in word.split("_") if part and part != word)
        if "\u3400" <= word[0] <= "\u9fff" and len(word) > 1:
            tokens.extend(word)
            tokens.extend(word[index:index + 2] for index in range(len(word) - 1))
    return tokens


class SearchIndex:
    def __init__(self, library, *, backend="bm25"):
        if backend != "bm25":
            raise ValueError("unsupported retrieval backend")
        self.entries = tuple(library)
        if len(self.entries) > 10000 or len({(item.id, item.version) for item in self.entries}) != len(self.entries):
            raise ValueError("invalid or duplicate IP catalog")
        corpus = [tokenize(" ".join((item.id, item.display_name, item.description, *item.tags,
                                     *(port.name for port in item.ports), *(parameter.name for parameter in item.parameters)))) for item in self.entries]
        self.postings = {}
        for index, tokens in enumerate(corpus):
            for token in set(tokens):
                self.postings.setdefault(token, set()).add(index)
        self.engine = BM25Plus(corpus) if corpus else None

    def search_ip(self, query, k=8, *, send_descriptions=False, builtin_descriptions=False):
        if not isinstance(query, str) or len(query) > 8000 or type(k) is not int or not 1 <= k <= 32:
            raise ValueError("invalid retrieval query or result count")
        tokens = tokenize(query)
        if not tokens or self.engine is None:
            return []
        matching = set().union(*(self.postings.get(token, ()) for token in tokens))
        if not matching:
            return []
        scores = self.engine.get_scores(tokens)
        named = set(WORDS.findall(query.casefold()))
        order = sorted(matching, key=lambda index: (self.entries[index].id.casefold() not in named, -float(scores[index]), self.entries[index].id, self.entries[index].version))
        return [metadata_card(self.entries[index], include_description=send_descriptions or builtin_descriptions and is_builtin_description(self.entries[index]))
            for index in order[:k]]


def search_ip(query, k=8, *, library):
    return SearchIndex(library).search_ip(query, k)