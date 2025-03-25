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


def sibling_jump(visible, cursor, direction, root_nodes, filter_set=None):
    """Jump to the next/prev parent sibling, landing on the matching key if possible.

    When the cursor is on a child key inside a container (e.g. 'port' inside
    services[0]), this jumps to the parent's next/prev sibling (services[1])
    and tries to land on the child with the same key ('port'). Falls back to
    the first child, or the sibling node itself if it isn't expanded.

    When the cursor is already on a top-level or root-level entry, it simply
    jumps to the next/prev entry at the same level.
    """
    node = visible[cursor]
    parent = node.parent

    if parent is None:
        # Top-level node: jump between root nodes
        siblings = root_nodes
        my_pos = next((i for i, s in enumerate(siblings) if s is node), None)
        if my_pos is None:
            return None
        target_pos = my_pos + direction
        if target_pos < 0 or target_pos >= len(siblings):
            return None
        target = siblings[target_pos]
        for i, v in enumerate(visible):
            if v is target:
                return i
        return None

    # Node has a parent — jump to matching key in parent's next sibling.
    grandparent = parent.parent
    parent_siblings = root_nodes if grandparent is None else grandparent.children

    parent_pos = next((i for i, s in enumerate(parent_siblings) if s is parent), None)
    if parent_pos is None:
        return None

    target_pos = parent_pos + direction
    if target_pos < 0 or target_pos >= len(parent_siblings):
        return None

    target_parent = parent_siblings[target_pos]

    # Auto-expand so the matching child is visible
    if target_parent.kind != "scalar" and not target_parent.expanded:
        target_parent.expanded = True

    if target_parent.expanded and target_parent.children:
        # Try to find a child with the same key
        for child in target_parent.children:
            if child.key == node.key:
                # Re-flatten since we may have expanded
                new_visible = flatten_visible(root_nodes, filter_set)
                for i, v in enumerate(new_visible):
                    if v is child:
                        return i
                break
        # Fallback: first child
        new_visible = flatten_visible(root_nodes)
        first = target_parent.children[0]
        for i, v in enumerate(new_visible):
            if v is first:
                return i

    # Not expandable: jump to the sibling itself
    new_visible = flatten_visible(root_nodes)
    for i, v in enumerate(new_visible):
        if v is target_parent:
            return i
    return None


def find_parent_index(visible, node):
    """Find the index of a node's parent in the visible list."""
    if node.parent is None:
        return None
    for i, n in enumerate(visible):
        if n is node.parent:
            return i
    return None


def draw_help(stdscr, height, width):
    """Draw the help panel."""
    lines = [
        "╭─── Shortcuts ───────────────────╮",
        "│                                  │",
        "│  ↑ / k      Move up              │",
        "│  ↓ / j      Move down            │",
        "│  J          Next sibling          │",
        "│  K          Previous sibling      │",
        "│  → / l      Expand node          │",
        "│  ← / h      Collapse / go parent │",
        "│  Space      Peek value (popup)    │",
        "│  Enter      Toggle expand         │",
        "│  e          Expand all            │",
        "│  x          Collapse all          │",
        "│  s          Sort object keys a-z  │",
        "│  g          Go to top             │",
        "│  G          Go to bottom          │",
        "│  /          Filter by key (fuzzy) │",
        "│  f          Filter by value       │",
        "│  n          Next match            │",
        "│  N          Previous match        │",
        "│  Esc        Clear filter          │",
        "│  c          Copy value to clipbrd │",
        "│  C          Copy key to clipboard  │",
        "│  ?          Toggle this help      │",
        "│  q          Quit                  │",
        "│                                  │",
        "╰──────────────────────────────────╯",
    ]
    start_y = max(0, (height - len(lines)) // 2)
    start_x = max(0, (width - len(lines[0])) // 2)
    for i, line in enumerate(lines):
        if start_y + i < height:
            try:
                stdscr.addstr(start_y + i, start_x, line, curses.color_pair(4))
            except curses.error:
                pass


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


def copy_to_clipboard(text):
    """Copy text to macOS clipboard via pbcopy."""
    import subprocess
    try:
        proc = subprocess.Popen(["pbcopy"], stdin=subprocess.PIPE)
        proc.communicate(text.encode("utf-8"))
    except FileNotFoundError:
        pass


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


def draw_tree_rows(win, nodes, cursor, scroll_offset, view_height, width,
                   y_offset=0, x_offset=0, filter_query="", filter_mode="key",
                   highlight_set=None):
    """Render tree rows into a curses window. Shared by main view and popup."""
    if highlight_set is None:
        highlight_set = set()
    visible = nodes  # already flattened
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

        x = x_offset
        row_y = y_offset + row_idx
        attr_base = curses.color_pair(6) | curses.A_BOLD if is_selected else 0

        try:
            win.addstr(row_y, x, indent, attr_base)
            x += len(indent)

            icon_attr = attr_base | (curses.color_pair(9) if not is_selected else 0)
            win.addstr(row_y, x, icon, icon_attr)
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
                if x >= x_offset + width - 1:
                    break
                attr = key_hi if ci in key_match_idx else key_base
                win.addstr(row_y, x, ch, attr)
                x += 1

            if val_str:
                sep = ": "
                win.addstr(row_y, x, sep, attr_base)
                x += len(sep)

                if node.kind == "scalar":
                    val_base = curses.color_pair(scalar_color_pair(node)) if not is_selected else curses.color_pair(6) | curses.A_BOLD
                else:
                    val_base = curses.color_pair(3) if not is_selected else curses.color_pair(6) | curses.A_BOLD
                val_hi = curses.color_pair(8) | curses.A_BOLD

                max_val_len = (x_offset + width) - x - 1
                display_val = val_str[:max_val_len] if len(val_str) > max_val_len else val_str
                for ci, ch in enumerate(display_val):
                    if x >= x_offset + width - 1:
                        break
                    attr = val_hi if ci in val_match_idx else val_base
                    win.addstr(row_y, x, ch, attr)
                    x += 1

            if is_selected:
                remaining = (x_offset + width) - x - 1
                if remaining > 0:
                    win.addstr(row_y, x, " " * remaining, curses.color_pair(6))
        except curses.error:
            pass


def show_value_popup(stdscr, source_node):
    """Show a navigable popup of the node's full value tree.

    Supports all navigation keys and recursive space for sub-popups.
    """
    screen_h, screen_w = stdscr.getmaxyx()
    p_h = max(7, screen_h * 4 // 5)
    p_w = max(30, screen_w * 4 // 5)
    p_y = (screen_h - p_h) // 2
    p_x = (screen_w - p_w) // 2

    win = curses.newwin(p_h, p_w, p_y, p_x)
    win.keypad(True)

    # Build fresh unfiltered tree from the node's raw value
    if source_node.kind == "scalar":
        # Simple scalar popup — just display the value
        while True:
            win.erase()
            win.border()
            title = f" {source_node.display_key()} "
            try:
                win.addstr(0, 2, title, curses.A_BOLD | curses.color_pair(1))
            except curses.error:
                pass
            val_text = repr(source_node.value)
            # Word-wrap long scalars
            inner_w = p_w - 4
            lines = [val_text[i:i + inner_w] for i in range(0, len(val_text), inner_w)]
            for i, line in enumerate(lines):
                if 2 + i >= p_h - 1:
                    break
                try:
                    win.addstr(2 + i, 2, line, curses.color_pair(scalar_color_pair(source_node)))
                except curses.error:
                    pass
            try:
                win.addstr(p_h - 1, 2, " Esc close  c copy ", curses.A_DIM)
            except curses.error:
                pass
            win.refresh()
            key = win.getch()
            if key == 27 or key == ord("q"):
                break
            elif key == ord("c"):
                if isinstance(source_node.value, str):
                    copy_to_clipboard(source_node.value)
                else:
                    copy_to_clipboard(json.dumps(source_node.value))
        del win
        stdscr.touchwin()
        stdscr.refresh()
        return

    # Complex value — build navigable tree
    if isinstance(source_node.value, dict):
        popup_roots = [JsonNode(k, v, depth=0) for k, v in source_node.value.items()]
    elif isinstance(source_node.value, list):
        popup_roots = [JsonNode(i, v, depth=0) for i, v in enumerate(source_node.value)]
    else:
        popup_roots = []

    cursor = 0
    scroll = 0
    content_h = p_h - 3  # border top + title line + border bottom

    while True:
        win.erase()
        win.border()

        title = f" {source_node.display_key()} "
        try:
            win.addstr(0, 2, title, curses.A_BOLD | curses.color_pair(1))
        except curses.error:
            pass

        visible = flatten_visible(popup_roots)
        if not visible:
            try:
                win.addstr(2, 2, "(empty)")
            except curses.error:
                pass
        else:
            cursor = max(0, min(cursor, len(visible) - 1))
            if cursor < scroll:
                scroll = cursor
            if cursor >= scroll + content_h:
                scroll = cursor - content_h + 1
            scroll = max(0, scroll)

            draw_tree_rows(win, visible, cursor, scroll, content_h,
                           p_w - 2, y_offset=1, x_offset=1)

        # Bottom hint
        try:
            hint = " Esc close  Space peek  c copy  ↑↓jk nav  ←h/→l fold "
            win.addstr(p_h - 1, 2, hint[:p_w - 4], curses.A_DIM)
        except curses.error:
            pass

        win.refresh()
        key = win.getch()

        if not visible:
            if key == 27 or key == ord("q"):
                break
            continue

        node = visible[cursor]

        if key == 27 or key == ord("q"):
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
                pidx = find_parent_index(visible, node)
                if pidx is not None:
                    visible[pidx].expanded = False
                    cursor = pidx
        elif key in (curses.KEY_ENTER, 10, 13):
            if node.kind != "scalar":
                node.expanded = not node.expanded
        elif key == ord("e"):
            expand_all(popup_roots)
        elif key == ord("x"):
            collapse_all(popup_roots)
            cursor = 0
            scroll = 0
        elif key == ord("g"):
            cursor = 0
            scroll = 0
        elif key == ord("G"):
            cursor = len(visible) - 1
        elif key == ord(" "):
            show_value_popup(stdscr, node)
            win.touchwin()
        elif key == ord("c"):
            if node.kind == "scalar":
                if isinstance(node.value, str):
                    copy_to_clipboard(node.value)
                else:
                    copy_to_clipboard(json.dumps(node.value))
            else:
                copy_to_clipboard(json.dumps(node.value, indent=2))
        elif key == ord("C"):
            copy_to_clipboard(str(node.display_key()))

    del win
    stdscr.touchwin()
    stdscr.refresh()


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
        C_HELP_FG = 255   # white
        C_HELP_BG = 236   # dark grey
        C_SEARCH_FG = 255
        C_SEARCH_BG = 238
        C_SEL_FG = 235    # near-black text
        C_SEL_BG = 110    # soft blue highlight
        C_INDEX = 183     # lavender — list indices
        C_MATCH_FG = 235
        C_MATCH_BG = 179  # gold highlight
        C_ICON = 245      # grey — expand/collapse arrows
        C_NULL = 167      # muted red — None
        C_BOOL = 215      # orange — booleans
        C_NUMBER = 80     # teal/cyan — numbers

        curses.init_pair(1, C_KEY, -1)
        curses.init_pair(2, C_STRING, -1)
        curses.init_pair(3, C_CONTAINER, -1)
        curses.init_pair(4, C_HELP_FG, C_HELP_BG)
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
        curses.init_pair(4, curses.COLOR_WHITE, curses.COLOR_BLACK)
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
    show_help = False
    filter_input_active = False   # True while typing in the filter bar
    filter_mode = "key"           # "key" or "value"
    filter_query = ""             # current filter text
    filter_set = None             # set of node ids to show (None = no filter)
    saved_expand = None           # expand state saved before filter
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
                elif key == ord(" "):
                    pass  # no nodes to peek at
                elif 32 <= key <= 126:
                    filter_query += chr(key)
            elif key == ord("q"):
                break
            continue

        cursor = max(0, min(cursor, len(visible) - 1))

        # Scroll so cursor is visible
        view_height = height - 2  # reserve bottom 2 lines for status
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

        # Draw rows using shared renderer
        draw_tree_rows(stdscr, visible, cursor, scroll_offset, view_height,
                       width, filter_query=filter_query, filter_mode=filter_mode,
                       highlight_set=highlight_set)

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

        # Bottom hint line
        try:
            hint = " ? help  q quit  / filter keys  f filter values  Esc clear"
            stdscr.addstr(height - 1, 0, hint[:width - 1], curses.A_DIM)
        except curses.error:
            pass

        if show_help:
            draw_help(stdscr, height, width)

        if filter_input_active:
            draw_filter_bar(stdscr, height, width, filter_query, filter_mode)

        stdscr.refresh()

        # Input
        key = stdscr.getch()
        status_msg = ""

        if filter_input_active:
            if key == 27:  # Escape — close input bar, keep filter active
                filter_input_active = False
                if not filter_query:
                    filter_set = None
                    if saved_expand:
                        restore_expand_state(root_nodes, saved_expand)
                        saved_expand = None
            elif key in (curses.KEY_ENTER, 10, 13):
                # Confirm filter — stop typing but keep the filter active
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
            elif key == ord(" "):
                # Space opens value popup even during filter input
                if visible:
                    show_value_popup(stdscr, visible[cursor])
            elif 32 <= key <= 126:
                filter_query += chr(key)
            continue

        if show_help:
            if key in (ord("?"), 27, ord("q")):
                show_help = False
            elif key == ord(" ") and visible:
                show_value_popup(stdscr, visible[cursor])
            continue

        node = visible[cursor]

        if key == 27:  # Escape — clear active filter
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
                # Collapse this node
                node.expanded = False
            elif node.parent is not None:
                # Navigate to parent
                parent_idx = find_parent_index(visible, node)
                if parent_idx is not None:
                    visible[parent_idx].expanded = False
                    cursor = parent_idx
        elif key in (curses.KEY_ENTER, 10, 13):
            if node.kind != "scalar":
                node.expanded = not node.expanded
        elif key == ord("?"):
            show_help = True
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
            # Jump to next direct match in filtered view
            if highlight_set:
                later = sorted(i for i in highlight_set if i > cursor)
                cursor = later[0] if later else min(highlight_set)
        elif key == ord("N"):
            if highlight_set:
                earlier = sorted((i for i in highlight_set if i < cursor), reverse=True)
                cursor = earlier[0] if earlier else max(highlight_set)
        elif key == ord("J"):
            idx = sibling_jump(visible, cursor, 1, root_nodes, filter_set)
            if idx is not None:
                cursor = idx
        elif key == ord("K"):
            idx = sibling_jump(visible, cursor, -1, root_nodes, filter_set)
            if idx is not None:
                cursor = idx
        elif key == ord("s"):
            # Remember current node's key to re-find after sort
            cur_key = visible[cursor].key
            cur_parent = visible[cursor].parent
            sort_objects_recursive(root_nodes)
            visible = flatten_visible(root_nodes)
            # Try to land back on the same node
            for i, v in enumerate(visible):
                if v.key == cur_key and v.parent is cur_parent:
                    cursor = i
                    break
            status_msg = "sorted objects alphabetically"
        elif key == ord("c"):
            if node.kind == "scalar":
                if isinstance(node.value, str):
                    copy_to_clipboard(node.value)
                    status_msg = f"copied: {node.value}"
                else:
                    copy_to_clipboard(json.dumps(node.value))
                    status_msg = f"copied: {json.dumps(node.value)}"
            else:
                text = json.dumps(node.value, indent=2)
                copy_to_clipboard(text)
                lines = text.count("\n") + 1
                status_msg = f"copied subtree ({lines} lines)"
        elif key == ord("C"):
            copy_to_clipboard(str(node.display_key()))
            status_msg = f"copied key: {node.display_key()}"
        elif key == ord(" "):
            show_value_popup(stdscr, node)


def run():
    if len(sys.argv) < 2:
        # Try reading from stdin
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
