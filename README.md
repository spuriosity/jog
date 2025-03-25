# jog

Interactive terminal JSON viewer. Feed it a JSON file, navigate the tree with vim-style keys, fuzzy-filter by key or value, copy paths to clipboard.

## Usage

```bash
./jog.py data.json
```

Or pipe it:
```bash
curl -s https://api.example.com/stuff | ./jog.py
```

## Keys

| Key | Action |
|-----|--------|
| `j`/`k` | Move up/down |
| `l`/`Enter` | Expand node |
| `h`/`Backspace` | Collapse / go to parent |
| `J`/`K` | Jump to next/prev sibling |
| `/` | Filter by key (fuzzy) |
| `f` | Filter by value |
| `c` | Copy value to clipboard |
| `C` | Copy key to clipboard |
| `Space` | Peek full value in popup |
| `s` | Sort object keys |
| `e`/`x` | Expand all / collapse all |
| `?` | Help |
| `q` | Quit |

## Why not jq?

jq is great for scripting. This is for when you want to poke around a big JSON blob interactively — exploring an API response, debugging a config file, that sort of thing.
