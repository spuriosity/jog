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


def main(stdscr, data):
    curses.curs_set(0)
    curses.use_default_colors()

    curses.init_pair(1, curses.COLOR_BLUE, -1)
    curses.init_pair(2, curses.COLOR_GREEN, -1)
    curses.init_pair(3, curses.COLOR_YELLOW, -1)

    # Build the root nodes
    if isinstance(data, dict):
        root_nodes = [JsonNode(k, v, depth=0) for k, v in data.items()]
    elif isinstance(data, list):
        root_nodes = [JsonNode(i, v, depth=0) for i, v in enumerate(data)]
    else:
        root_nodes = [JsonNode("(root)", data, depth=0)]

    cursor = 0
    scroll_offset = 0

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

            line = f"{indent}{icon}{key_str}"
            if val_str:
                line += f": {val_str}"

            attr = curses.A_REVERSE if is_selected else 0
            if not is_selected:
                if node.kind == "scalar":
                    attr = curses.color_pair(2)
                elif isinstance(node.key, int):
                    attr = curses.color_pair(3)
                else:
                    attr = curses.color_pair(1)

            try:
                stdscr.addstr(row_idx, 0, line[:width - 1], attr)
            except curses.error:
                pass

        # Status bar
        try:
            bar = f" {cursor + 1}/{len(visible)}  depth:{visible[cursor].depth}"
            bar = bar.ljust(width - 1)
            stdscr.addstr(height - 2, 0, bar[:width - 1], curses.A_REVERSE)
        except curses.error:
            pass

        try:
            stdscr.addstr(height - 1, 0, " q quit  ↑↓/jk nav  ←h/→l fold  Enter toggle", curses.A_DIM)
        except curses.error:
            pass

        stdscr.refresh()

        key = stdscr.getch()

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
