# List Merger for Home Assistant

[![hacs_badge](https://img.shields.io/badge/HACS-Custom-orange.svg)](https://github.com/hacs/integration)

A HACS integration that merges multiple Home Assistant **todo lists** into one master list — in real time, event-driven.

## Features

- **Merge any todo lists** — works with any HA todo entity (Mealie, eTilbudsavis, OurGroceries, Simple Inventory, etc.)
- **Per-source sync direction** — one-way (source → master) or two-way (source ↔ master) per list
- **Delete on merge** — optionally remove items from the source list once they land on master
- **Duplicate handling** — deduplicate by name (case-insensitive) or keep all copies
- **Completed item behaviour** — choose one of:
  - Sync completion back to the source list
  - Only mark as complete on master
  - Delete from both master and source
- **New or existing master** — create a fresh virtual list or merge into an existing one
- **Persistent** — survives HA restarts; only newly added items are synced on reload

## Installation via HACS

1. Open HACS → Integrations → Custom repositories
2. Add `https://github.com/cagosdk/hacs-listmerger` as type **Integration**
3. Install **List Merger**
4. Restart Home Assistant

## Setup

1. Go to **Settings → Devices & Services → Add integration**
2. Search for **List Merger**
3. Follow the config flow:
   - Give the merger a name
   - Choose to create a new virtual list or use an existing one
   - Pick duplicate handling and completed-item behaviour
   - Select your source lists
   - Configure each source individually (sync direction + delete-on-merge)

You can reconfigure sources and settings at any time via the integration's **Configure** button.

## Example: eTilbudsavis + Mealie + Simple Inventory → one shopping list

| Source | Direction | Delete on merge |
|---|---|---|
| `todo.etilbudsavis_cart` | One-way | Yes |
| `todo.mealie_shopping` | Two-way | No |
| `todo.low_stock_items` | One-way | Yes |

This setup pulls deals from eTilbudsavis and low-stock items into the master shopping list, while Mealie stays in two-way sync so anything you add to master also appears in Mealie.

## Minimum requirements

- Home Assistant 2023.11 or newer
- HACS 1.x

## License

MIT
