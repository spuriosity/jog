#!/usr/bin/env python3
"""Interactive JSON viewer with collapsible keys using curses."""

import curses
import json
import sys


class JsonNode:
    """Represents a node in the JSON tree."""

    def __init__(self, key, value, depth=0, parent=None):
        self.key = key
        self.value = value
        self.depth = depth
        self.parent = parent
        self.expanded = False
        self.children = []

        if isinstance(value, dict):
            self.kind = "object"
            for k, v in value.items():
                self.children.append(JsonNode(k, v, depth + 1, parent=self))
        elif isinstance(value, list):
            self.kind = "list"
            for i, v in enumerate(value):
                self.children.append(JsonNode(i, v, depth + 1, parent=self))
        else:
            self.kind = "scalar"

    def display_value(self):
        if self.kind == "object":
            if self.expanded:
                return ""
            n = len(self.value)
            if n == 0:
                return "{}"
            return f"{{...}} ({n} key{'s' if n != 1 else ''})"
        elif self.kind == "list":
            if self.expanded:
                return ""
            n = len(self.value)
            if n == 0:
                return "[]"
            return f"[...] ({n} item{'s' if n != 1 else ''})"
        else:
            return repr(self.value)

    def display_key(self):
        if isinstance(self.key, int):
            return f"[{self.key}]"
        return self.key


def sort_objects_recursive(nodes):
    """Sort children of every object node alphabetically by key, at all levels."""
    for node in nodes:
        if node.kind == "object":
            node.children.sort(key=lambda n: str(n.key).lower())
        sort_objects_recursive(node.children)


def fuzzy_match(pattern, text):
    """True if every character in pattern appears in text in order (case-insensitive)."""
    if not pattern:
        return True
    p = pattern.lower()
    t = text.lower()
    pi = 0
    for ch in t:
        if ch == p[pi]:
            pi += 1
            if pi == len(p):
                return True
    return False


def fuzzy_match_indices(pattern, text):
    """Return the set of character indices in text that match the fuzzy pattern.

    Returns None if the pattern doesn't match at all.
    """
    if not pattern:
        return set()
    p = pattern.lower()
    t = text.lower()
    pi = 0
    indices = set()
    for i, ch in enumerate(t):
        if pi < len(p) and ch == p[pi]:
            indices.add(i)
            pi += 1
    if pi == len(p):
        return indices
    return None


def collect_all_nodes(nodes):
    """Yield every node in the tree."""
    for node in nodes:
        yield node
        yield from collect_all_nodes(node.children)


def save_expand_state(nodes):
    """Save expanded state for every node, keyed by id."""
    state = {}
    for node in collect_all_nodes(nodes):
        state[id(node)] = node.expanded
    return state


def restore_expand_state(nodes, state):
    """Restore previously saved expanded state."""
    for node in collect_all_nodes(nodes):
        if id(node) in state:
            node.expanded = state[id(node)]


def compute_filter_set(nodes, query, mode):
    """Return the set of node ids that should be visible under the filter.

    mode="key":   fuzzy match against node key
    mode="value": fuzzy match against scalar value representation

    A node is included if it directly matches OR any descendant matches.
    All ancestors of matching nodes are included so the tree path is visible.
    """
    direct_matches = set()

    def walk(node):
        matched = False
        if mode == "key":
            matched = fuzzy_match(query, str(node.display_key()))
        elif mode == "value" and node.kind == "scalar":
            matched = fuzzy_match(query, repr(node.value))

        child_matched = False
        for child in node.children:
            if walk(child):
                child_matched = True

        if matched or child_matched:
            direct_matches.add(id(node))
            return True
        return False

    for node in nodes:
        walk(node)

    return direct_matches


def flatten_visible(nodes, filter_set=None):
    """Flatten the tree into a list of visible nodes.

    If filter_set is provided, only nodes whose id is in the set are shown,
    and containers with matching descendants are force-expanded.
    """
    result = []
    for node in nodes:
        if filter_set is not None and id(node) not in filter_set:
            continue
        result.append(node)
        if node.children:
            if filter_set is not None:
                # Force-expand containers that are in the filter set
                has_filtered_children = any(
                    id(c) in filter_set for c in node.children
                )
                if has_filtered_children:
                    result.extend(flatten_visible(node.children, filter_set))
            elif node.expanded:
                result.extend(flatten_visible(node.children))
    return result


def find_parent_index(visible, node):
    """Find the index of a node's parent in the visible list."""
    if node.parent is None:
        return None
    for i, n in enumerate(visible):
        if n is node.parent:
            return i
    return None


def draw_filter_bar(stdscr, height, width, query, mode):
    """Draw the filter input bar at the bottom."""
    prefix = "/" if mode == "key" else "f/"
    try:
        stdscr.addstr(height - 1, 0, " " * (width - 1), curses.color_pair(5))
        stdscr.addstr(height - 1, 0, f" {prefix}{query}", curses.color_pair(5))
    except curses.error:
        pass


def expand_all(nodes):
    for node in nodes:
        if node.kind != "scalar":
            node.expanded = True
        expand_all(node.children)


def collapse_all(nodes):
    for node in nodes:
        node.expanded = False
        collapse_all(node.children)


def scalar_color_pair(node):
    """Return the color pair number for a scalar node based on its Python type."""
    v = node.value
    if v is None:
        return 10  # null/None — muted red
    elif isinstance(v, bool):
        return 11  # bool — orange/yellow
    elif isinstance(v, (int, float)):
        return 12  # number — cyan
    else:
        return 2   # string — green


def main(stdscr, data):
    curses.curs_set(0)
    curses.use_default_colors()

    # Attempt 256-color definitions; fall back to basic 8 if unsupported
    use_256 = curses.COLORS >= 256

    if use_256:
        C_KEY = 110
        C_STRING = 120
        C_CONTAINER = 179
        C_SEARCH_FG = 255
        C_SEARCH_BG = 238
        C_SEL_FG = 235
        C_SEL_BG = 110
        C_INDEX = 183
        C_MATCH_FG = 235
        C_MATCH_BG = 179
        C_ICON = 245
        C_NULL = 167
        C_BOOL = 215
        C_NUMBER = 80

        curses.init_pair(1, C_KEY, -1)
        curses.init_pair(2, C_STRING, -1)
        curses.init_pair(3, C_CONTAINER, -1)
        curses.init_pair(5, C_SEARCH_FG, C_SEARCH_BG)
        curses.init_pair(6, C_SEL_FG, C_SEL_BG)
        curses.init_pair(7, C_INDEX, -1)
        curses.init_pair(8, C_MATCH_FG, C_MATCH_BG)
        curses.init_pair(9, C_ICON, -1)
        curses.init_pair(10, C_NULL, -1)
        curses.init_pair(11, C_BOOL, -1)
        curses.init_pair(12, C_NUMBER, -1)
    else:
        curses.init_pair(1, curses.COLOR_BLUE, -1)
        curses.init_pair(2, curses.COLOR_GREEN, -1)
        curses.init_pair(3, curses.COLOR_YELLOW, -1)
        curses.init_pair(5, curses.COLOR_WHITE, curses.COLOR_BLACK)
        curses.init_pair(6, curses.COLOR_BLACK, curses.COLOR_BLUE)
        curses.init_pair(7, curses.COLOR_MAGENTA, -1)
        curses.init_pair(8, curses.COLOR_BLACK, curses.COLOR_YELLOW)
        curses.init_pair(9, curses.COLOR_WHITE, -1)
        curses.init_pair(10, curses.COLOR_RED, -1)
        curses.init_pair(11, curses.COLOR_YELLOW, -1)
        curses.init_pair(12, curses.COLOR_CYAN, -1)

    # Build the root nodes
    if isinstance(data, dict):
        root_nodes = [JsonNode(k, v, depth=0) for k, v in data.items()]
    elif isinstance(data, list):
        root_nodes = [JsonNode(i, v, depth=0) for i, v in enumerate(data)]
    else:
        root_nodes = [JsonNode("(root)", data, depth=0)]

    cursor = 0
    scroll_offset = 0
    filter_input_active = False
    filter_mode = "key"
    filter_query = ""
    filter_set = None
    saved_expand = None
    status_msg = ""

    while True:
        stdscr.erase()
        height, width = stdscr.getmaxyx()

        # Recompute filter set from query (live as you type)
        if filter_query:
            filter_set = compute_filter_set(root_nodes, filter_query, filter_mode)
        elif not filter_input_active:
            filter_set = None

        visible = flatten_visible(root_nodes, filter_set)
        if not visible:
            msg = "(no matches)" if filter_set is not None else "(empty JSON)"
            stdscr.addstr(0, 0, msg)
            if filter_input_active:
                draw_filter_bar(stdscr, height, width, filter_query, filter_mode)
            stdscr.refresh()
            key = stdscr.getch()
            if filter_input_active:
                if key == 27:
                    filter_input_active = False
                    if not filter_query:
                        filter_set = None
                        if saved_expand:
                            restore_expand_state(root_nodes, saved_expand)
                            saved_expand = None
                elif key in (curses.KEY_BACKSPACE, 127, 8):
                    filter_query = filter_query[:-1]
                elif 32 <= key <= 126:
                    filter_query += chr(key)
            elif key == ord("q"):
                break
            continue

        cursor = max(0, min(cursor, len(visible) - 1))

        view_height = height - 2
        if cursor < scroll_offset:
            scroll_offset = cursor
        if cursor >= scroll_offset + view_height:
            scroll_offset = cursor - view_height + 1
        scroll_offset = max(0, scroll_offset)

        # Determine which visible nodes are direct fuzzy matches (for highlighting)
        highlight_set = set()
        if filter_query:
            for i, node in enumerate(visible):
                if filter_mode == "key" and fuzzy_match(filter_query, str(node.display_key())):
                    highlight_set.add(i)
                elif filter_mode == "value" and node.kind == "scalar" and fuzzy_match(filter_query, repr(node.value)):
                    highlight_set.add(i)

        # Draw rows
        for row_idx in range(view_height):
            node_idx = scroll_offset + row_idx
            if node_idx >= len(visible):
                break
            node = visible[node_idx]
            indent = "  " * node.depth
            is_selected = node_idx == cursor
            is_match = node_idx in highlight_set

            if node.kind in ("object", "list"):
                icon = "▼ " if node.expanded else "▶ "
            else:
                icon = "  "

            key_str = node.display_key()
            val_str = node.display_value()

            x = 0
            attr_base = curses.color_pair(6) | curses.A_BOLD if is_selected else 0

            try:
                stdscr.addstr(row_idx, x, indent, attr_base)
                x += len(indent)

                icon_attr = attr_base | (curses.color_pair(9) if not is_selected else 0)
                stdscr.addstr(row_idx, x, icon, icon_attr)
                x += len(icon)

                # Per-character highlight indices
                key_match_idx = set()
                val_match_idx = set()
                if is_match and not is_selected and filter_query:
                    if filter_mode == "key":
                        key_match_idx = fuzzy_match_indices(filter_query, str(key_str)) or set()
                    elif filter_mode == "value" and node.kind == "scalar":
                        val_match_idx = fuzzy_match_indices(filter_query, val_str) or set()

                if isinstance(node.key, int):
                    key_base = curses.color_pair(7) if not is_selected else curses.color_pair(6) | curses.A_BOLD
                else:
                    key_base = curses.color_pair(1) if not is_selected else curses.color_pair(6) | curses.A_BOLD
                key_hi = curses.color_pair(8) | curses.A_BOLD
                key_text = str(key_str)
                for ci, ch in enumerate(key_text):
                    if x >= width - 1:
                        break
                    attr = key_hi if ci in key_match_idx else key_base
                    stdscr.addstr(row_idx, x, ch, attr)
                    x += 1

                if val_str:
                    stdscr.addstr(row_idx, x, ": ", attr_base)
                    x += 2

                    if node.kind == "scalar":
                        val_base = curses.color_pair(scalar_color_pair(node)) if not is_selected else curses.color_pair(6) | curses.A_BOLD
                    else:
                        val_base = curses.color_pair(3) if not is_selected else curses.color_pair(6) | curses.A_BOLD
                    val_hi = curses.color_pair(8) | curses.A_BOLD

                    max_val_len = width - x - 1
                    display_val = val_str[:max_val_len] if len(val_str) > max_val_len else val_str
                    for ci, ch in enumerate(display_val):
                        if x >= width - 1:
                            break
                        attr = val_hi if ci in val_match_idx else val_base
                        stdscr.addstr(row_idx, x, ch, attr)
                        x += 1

                if is_selected:
                    remaining = width - x - 1
                    if remaining > 0:
                        stdscr.addstr(row_idx, x, " " * remaining, curses.color_pair(6))
            except curses.error:
                pass

        # Status bar
        status_y = height - 2
        try:
            bar = f" {cursor + 1}/{len(visible)}  depth:{visible[cursor].depth}"
            if filter_query:
                mode_label = "key" if filter_mode == "key" else "value"
                bar += f"  filter({mode_label}):'{filter_query}' ({len(highlight_set)} matches)"
            if status_msg:
                bar += f"  {status_msg}"
            bar = bar.ljust(width - 1)
            stdscr.addstr(status_y, 0, bar[:width - 1], curses.A_REVERSE)
        except curses.error:
            pass

        try:
            hint = " q quit  / filter keys  f filter values  n/N next/prev match  Esc clear"
            stdscr.addstr(height - 1, 0, hint[:width - 1], curses.A_DIM)
        except curses.error:
            pass

        if filter_input_active:
            draw_filter_bar(stdscr, height, width, filter_query, filter_mode)

        stdscr.refresh()

        key = stdscr.getch()
        status_msg = ""

        if filter_input_active:
            if key == 27:
                filter_input_active = False
                if not filter_query:
                    filter_set = None
                    if saved_expand:
                        restore_expand_state(root_nodes, saved_expand)
                        saved_expand = None
            elif key in (curses.KEY_ENTER, 10, 13):
                filter_input_active = False
                if not filter_query:
                    filter_set = None
                    if saved_expand:
                        restore_expand_state(root_nodes, saved_expand)
                        saved_expand = None
            elif key in (curses.KEY_BACKSPACE, 127, 8):
                filter_query = filter_query[:-1]
            elif key in (curses.KEY_UP,):
                cursor = max(0, cursor - 1)
            elif key in (curses.KEY_DOWN,):
                cursor = min(len(visible) - 1, cursor + 1)
            elif 32 <= key <= 126:
                filter_query += chr(key)
            continue

        node = visible[cursor]

        if key == 27:
            if filter_query:
                filter_query = ""
                filter_set = None
                if saved_expand:
                    restore_expand_state(root_nodes, saved_expand)
                    saved_expand = None
                cursor = 0
                scroll_offset = 0
                continue
            else:
                break
        elif key == ord("q"):
            break
        elif key in (curses.KEY_UP, ord("k")):
            cursor = max(0, cursor - 1)
        elif key in (curses.KEY_DOWN, ord("j")):
            cursor = min(len(visible) - 1, cursor + 1)
        elif key in (curses.KEY_RIGHT, ord("l")):
            if node.kind != "scalar" and not node.expanded:
                node.expanded = True
        elif key in (curses.KEY_LEFT, ord("h")):
            if node.expanded and node.kind != "scalar":
                node.expanded = False
            elif node.parent is not None:
                parent_idx = find_parent_index(visible, node)
                if parent_idx is not None:
                    visible[parent_idx].expanded = False
                    cursor = parent_idx
        elif key in (curses.KEY_ENTER, 10, 13):
            if node.kind != "scalar":
                node.expanded = not node.expanded
        elif key == ord("e"):
            expand_all(root_nodes)
        elif key == ord("x"):
            collapse_all(root_nodes)
            cursor = 0
            scroll_offset = 0
        elif key == ord("g"):
            cursor = 0
            scroll_offset = 0
        elif key == ord("G"):
            cursor = len(visible) - 1
        elif key == ord("/"):
            filter_input_active = True
            filter_mode = "key"
            filter_query = ""
            saved_expand = save_expand_state(root_nodes)
        elif key == ord("f"):
            filter_input_active = True
            filter_mode = "value"
            filter_query = ""
            saved_expand = save_expand_state(root_nodes)
        elif key == ord("n"):
            if highlight_set:
                later = sorted(i for i in highlight_set if i > cursor)
                cursor = later[0] if later else min(highlight_set)
        elif key == ord("N"):
            if highlight_set:
                earlier = sorted((i for i in highlight_set if i < cursor), reverse=True)
                cursor = earlier[0] if earlier else max(highlight_set)
        elif key == ord("s"):
            cur_key = visible[cursor].key
            cur_parent = visible[cursor].parent
            sort_objects_recursive(root_nodes)
            visible = flatten_visible(root_nodes)
            for i, v in enumerate(visible):
                if v.key == cur_key and v.parent is cur_parent:
                    cursor = i
                    break
            status_msg = "sorted objects alphabetically"


def run():
    if len(sys.argv) < 2:
        if not sys.stdin.isatty():
            raw = sys.stdin.read()
        else:
            print("Usage: jog <file.json>")
            print("       cat file.json | jog -")
            sys.exit(1)
    elif sys.argv[1] == "-":
        raw = sys.stdin.read()
    else:
        with open(sys.argv[1]) as f:
            raw = f.read()

    try:
        data = json.loads(raw)
    except json.JSONDecodeError as e:
        print(f"Invalid JSON: {e}")
        sys.exit(1)

    curses.wrapper(lambda stdscr: main(stdscr, data))


if __name__ == "__main__":
    run()
