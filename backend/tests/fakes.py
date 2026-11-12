"""In-memory stand-ins for MongoDB (motor) and a Pinecone index.

Just enough of each API for the offline tests: no network, no services.
"""
import copy


# ---------- Mongo ----------
def _matches(doc: dict, query: dict) -> bool:
    for key, cond in query.items():
        value = doc.get(key)  # missing behaves like None, as in Mongo
        if isinstance(cond, dict) and "$in" in cond:
            if value not in cond["$in"]:
                return False
        elif value != cond:
            return False
    return True


def _project(doc: dict, projection: dict | None) -> dict:
    doc = copy.deepcopy(doc)
    for key, keep in (projection or {}).items():
        if not keep:
            doc.pop(key, None)
    return doc


class FakeCursor:
    def __init__(self, rows: list[dict]):
        self._rows = rows
        self._pos = 0

    def sort(self, key, direction=1):
        if isinstance(key, list):
            key, direction = key[0]
        self._rows.sort(key=lambda r: r.get(key) or "", reverse=direction < 0)
        return self

    async def to_list(self, length=None):
        end = len(self._rows) if length is None else self._pos + length
        out = self._rows[self._pos : end]
        self._pos += len(out)
        return out


class _Result:
    def __init__(self, deleted_count=0):
        self.deleted_count = deleted_count


class FakeCollection:
    def __init__(self):
        self.rows: list[dict] = []

    def find(self, query=None, projection=None):
        return FakeCursor(
            [_project(r, projection) for r in self.rows if _matches(r, query or {})]
        )

    async def find_one(self, query, projection=None):
        for r in self.rows:
            if _matches(r, query):
                return _project(r, projection)
        return None

    async def count_documents(self, query):
        return sum(1 for r in self.rows if _matches(r, query))

    async def insert_one(self, doc):
        self.rows.append(copy.deepcopy(doc))

    async def insert_many(self, docs):
        self.rows.extend(copy.deepcopy(d) for d in docs)

    async def update_one(self, query, update, upsert=False):
        for r in self.rows:
            if _matches(r, query):
                r.update(copy.deepcopy(update["$set"]))
                return _Result()
        if upsert:
            self.rows.append(copy.deepcopy(update["$set"]))
        return _Result()

    async def update_many(self, query, update):
        for r in self.rows:
            if _matches(r, query):
                r.update(copy.deepcopy(update["$set"]))
        return _Result()

    async def delete_one(self, query):
        for i, r in enumerate(self.rows):
            if _matches(r, query):
                del self.rows[i]
                return _Result(1)
        return _Result(0)

    async def delete_many(self, query):
        before = len(self.rows)
        self.rows = [r for r in self.rows if not _matches(r, query)]
        return _Result(before - len(self.rows))

    async def create_index(self, *args, **kwargs):
        return None


class FakeDB:
    def __init__(self):
        self._collections: dict[str, FakeCollection] = {}

    def __getattr__(self, name):
        if name.startswith("_"):
            raise AttributeError(name)
        return self._collections.setdefault(name, FakeCollection())


# ---------- Pinecone ----------
class FakeIndex:
    """Serverless-like index: upsert / query / list(prefix) / delete."""

    def __init__(self, page_size: int = 2):
        self.vectors: dict[str, dict] = {}
        self.namespaces_seen: set = set()
        self.fail_delete = False
        self.page_size = page_size
        self.upsert_threads: list[str] = []

    def upsert(self, vectors, namespace=None):
        import threading

        self.namespaces_seen.add(namespace)
        self.upsert_threads.append(threading.current_thread().name)
        for v in vectors:
            self.vectors[v["id"]] = v

    def list(self, prefix, namespace=None):
        self.namespaces_seen.add(namespace)
        ids = sorted(i for i in self.vectors if i.startswith(prefix))
        for i in range(0, len(ids), self.page_size):
            yield ids[i : i + self.page_size]

    def delete(self, ids, namespace=None):
        if self.fail_delete:
            from pinecone.exceptions import PineconeException

            raise PineconeException("simulated delete failure")
        for i in ids:
            self.vectors.pop(i, None)
