import heapq


class SortedDict(dict):
    def __init__(self, sort_func=lambda k, v: k, init_dict=None, reverse=False):
        if init_dict is None:
            init_dict = []
        if isinstance(init_dict, dict):
            init_dict = init_dict.items()
        self.sort_func = sort_func
        self.sorted_keys = None
        self.reverse = reverse
        self.heap = []
        for k, v in init_dict:
            self[k] = v

    def __setitem__(self, key, value):
        if key in self:
            super().__setitem__(key, value)
            for i, (priority, k) in enumerate(self.heap):
                if k == key:
                    self.heap[i] = (self.sort_func(key, value), key)
                    heapq.heapify(self.heap)
                    break
            self.sorted_keys = None
        else:
            super().__setitem__(key, value)
            heapq.heappush(self.heap, (self.sort_func(key, value), key))
            self.sorted_keys = None

    def __delitem__(self, key):
        super().__delitem__(key)
        for i, (priority, k) in enumerate(self.heap):
            if k == key:
                del self.heap[i]
                heapq.heapify(self.heap)
                break
        self.sorted_keys = None

    def clear(self):
        super().clear()
        self.heap.clear()
        self.sorted_keys = None

    def update(self, *args, **kwargs):
        for key, value in dict(*args, **kwargs).items():
            self[key] = value

    def setdefault(self, key, default=None):
        if key not in self:
            self[key] = default
        return self[key]

    def pop(self, key, *defaults):
        if len(defaults) > 1:
            raise TypeError(f"pop expected at most 2 arguments, got {1 + len(defaults)}")
        if key not in self:
            if defaults:
                return defaults[0]
            raise KeyError(key)
        value = self[key]
        del self[key]
        return value

    def popitem(self):
        if not self:
            raise KeyError("popitem(): dictionary is empty")
        key = next(reversed(super().keys()))
        return key, self.pop(key)

    def __ior__(self, other):
        self.update(other)
        return self

    def values(self):
        return [self[key] for key in self.keys()]

    def keys(self):
        if self.sorted_keys is None:
            self.sorted_keys = [k for _, k in sorted(self.heap, reverse=self.reverse)]
        return self.sorted_keys

    def items(self):
        if self.sorted_keys is None:
            self.sorted_keys = [k for _, k in sorted(self.heap, reverse=self.reverse)]
        sorted_items = [(k, self[k]) for k in self.sorted_keys]
        return sorted_items

    def _update_heap(self, key):
        for i, (priority, k) in enumerate(self.heap):
            if k == key:
                new_priority = self.sort_func(key, self[key])
                if new_priority != priority:
                    self.heap[i] = (new_priority, key)
                    heapq.heapify(self.heap)
                    self.sorted_keys = None
                break

    def __iter__(self):
        return iter(self.keys())

    def __repr__(self):
        return f"{type(self).__name__}({dict(self)}, sort_func={self.sort_func.__name__}, reverse={self.reverse})"
