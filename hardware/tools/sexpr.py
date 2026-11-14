"""Minimal S-expression reader/writer for KiCad files.

Atoms are kept as Python strings. Quoted strings become `Q` instances so they are
written back quoted; bare atoms stay plain `str`.
"""


class Q(str):
    """A quoted string atom."""


def parse(text):
    pos = 0
    n = len(text)

    def skip_ws(i):
        while i < n and text[i] in " \t\r\n":
            i += 1
        return i

    def read(i):
        i = skip_ws(i)
        c = text[i]
        if c == "(":
            lst = []
            i += 1
            while True:
                i = skip_ws(i)
                if text[i] == ")":
                    return lst, i + 1
                item, i = read(i)
                lst.append(item)
        if c == '"':
            j = i + 1
            buf = []
            while text[j] != '"':
                if text[j] == "\\":
                    nxt = text[j + 1]
                    buf.append({"n": "\n", "t": "\t", '"': '"', "\\": "\\"}.get(nxt, nxt))
                    j += 2
                else:
                    buf.append(text[j])
                    j += 1
            return Q("".join(buf)), j + 1
        j = i
        while j < n and text[j] not in " \t\r\n()":
            j += 1
        return text[i:j], j

    node, pos = read(pos)
    return node


def _esc(s):
    return s.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n")


def dumps(node, indent=0):
    """Serialize in KiCad's style: one list per line, tab indented."""
    if isinstance(node, Q):
        return '"%s"' % _esc(node)
    if isinstance(node, str):
        return node
    if isinstance(node, (int, float)):
        return fmt_num(node)
    # list
    simple = all(not isinstance(x, list) for x in node)
    if simple:
        return "(" + " ".join(dumps(x) for x in node) + ")"
    tab = "\t" * (indent + 1)
    parts = []
    head = []
    for x in node:
        if isinstance(x, list):
            break
        head.append(dumps(x))
    out = "(" + " ".join(head)
    rest = node[len(head):]
    for x in rest:
        if isinstance(x, list):
            # keep (pts (xy ..) (xy ..)) style short lists inline
            out += "\n" + tab + dumps(x, indent + 1)
        else:
            out += " " + dumps(x)
    out += "\n" + "\t" * indent + ")"
    return out


def fmt_num(v):
    if isinstance(v, int):
        return str(v)
    s = ("%.4f" % v).rstrip("0").rstrip(".")
    if s in ("-0", ""):
        s = "0"
    return s


def find(node, key):
    """First child list whose head is `key`."""
    for x in node:
        if isinstance(x, list) and x and x[0] == key:
            return x
    return None


def find_all(node, key):
    return [x for x in node if isinstance(x, list) and x and x[0] == key]
