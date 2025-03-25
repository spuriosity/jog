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


def flatten_visible(nodes, filter_set=None):
    """Flatten the tree into a list of visible nodes."""
    result = []
    for node in nodes:
        if filter_set is not None and id(node) not in filter_set:
            continue
        result.append(node)
        if node.children and node.expanded:
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
        # Catppuccin Mocha-inspired palette (on default terminal bg)
        C_KEY = 110       # soft blue — object keys
        C_STRING = 120    # muted green — strings
        C_CONTAINER = 179 # warm gold — collapsed {…}/[…]
        C_SEL_FG = 235    # near-black text
        C_SEL_BG = 110    # soft blue highlight
        C_INDEX = 183     # lavender — list indices
        C_ICON = 245      # grey — expand/collapse arrows
        C_NULL = 167      # muted red — None
        C_BOOL = 215      # orange — booleans
        C_NUMBER = 80     # teal/cyan — numbers

        curses.init_pair(1, C_KEY, -1)
        curses.init_pair(2, C_STRING, -1)
        curses.init_pair(3, C_CONTAINER, -1)
        curses.init_pair(6, C_SEL_FG, C_SEL_BG)
        curses.init_pair(7, C_INDEX, -1)
        curses.init_pair(9, C_ICON, -1)
        curses.init_pair(10, C_NULL, -1)
        curses.init_pair(11, C_BOOL, -1)
        curses.init_pair(12, C_NUMBER, -1)
    else:
        curses.init_pair(1, curses.COLOR_BLUE, -1)
        curses.init_pair(2, curses.COLOR_GREEN, -1)
        curses.init_pair(3, curses.COLOR_YELLOW, -1)
        curses.init_pair(6, curses.COLOR_BLACK, curses.COLOR_BLUE)
        curses.init_pair(7, curses.COLOR_MAGENTA, -1)
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
    status_msg = ""

    while True:
        stdscr.erase()
        height, width = stdscr.getmaxyx()

        visible = flatten_visible(root_nodes)
        if not visible:
            stdscr.addstr(0, 0, "(empty JSON)")
            stdscr.refresh()
            key = stdscr.getch()
            if key == ord("q"):
                break
            continue

        cursor = max(0, min(cursor, len(visible) - 1))

        view_height = height - 2
        if cursor < scroll_offset:
            scroll_offset = cursor
        if cursor >= scroll_offset + view_height:
            scroll_offset = cursor - view_height + 1
        scroll_offset = max(0, scroll_offset)

        # Draw rows
        for row_idx in range(view_height):
            node_idx = scroll_offset + row_idx
            if node_idx >= len(visible):
                break
            node = visible[node_idx]
            indent = "  " * node.depth
            is_selected = node_idx == cursor

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

                if isinstance(node.key, int):
                    key_attr = curses.color_pair(7) if not is_selected else curses.color_pair(6) | curses.A_BOLD
                else:
                    key_attr = curses.color_pair(1) if not is_selected else curses.color_pair(6) | curses.A_BOLD
                stdscr.addstr(row_idx, x, str(key_str), key_attr)
                x += len(str(key_str))

                if val_str:
                    stdscr.addstr(row_idx, x, ": ", attr_base)
                    x += 2

                    if node.kind == "scalar":
                        val_attr = curses.color_pair(scalar_color_pair(node)) if not is_selected else curses.color_pair(6) | curses.A_BOLD
                    else:
                        val_attr = curses.color_pair(3) if not is_selected else curses.color_pair(6) | curses.A_BOLD

                    max_val_len = width - x - 1
                    display_val = val_str[:max_val_len] if len(val_str) > max_val_len else val_str
                    stdscr.addstr(row_idx, x, display_val, val_attr)
                    x += len(display_val)

                if is_selected:
                    remaining = width - x - 1
                    if remaining > 0:
                        stdscr.addstr(row_idx, x, " " * remaining, curses.color_pair(6))
            except curses.error:
                pass

        # Status bar
        try:
            bar = f" {cursor + 1}/{len(visible)}  depth:{visible[cursor].depth}"
            if status_msg:
                bar += f"  {status_msg}"
            bar = bar.ljust(width - 1)
            stdscr.addstr(height - 2, 0, bar[:width - 1], curses.A_REVERSE)
        except curses.error:
            pass

        try:
            stdscr.addstr(height - 1, 0, " q quit  ↑↓/jk nav  ←h/→l fold  Enter toggle  e expand all  x collapse  s sort", curses.A_DIM)
        except curses.error:
            pass

        stdscr.refresh()

        key = stdscr.getch()
        status_msg = ""

        node = visible[cursor]

        if key == ord("q") or key == 27:
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
        elif key == ord("g"):
            cursor = 0
            scroll_offset = 0
        elif key == ord("G"):
            cursor = len(visible) - 1
        elif key == ord("e"):
            expand_all(root_nodes)
        elif key == ord("x"):
            collapse_all(root_nodes)
            cursor = 0
            scroll_offset = 0
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
